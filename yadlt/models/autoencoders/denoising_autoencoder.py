"""Implementation of Denoising Autoencoder using TensorFlow."""

from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow as tf
from tqdm import tqdm

from yadlt.core import Layers, Loss, Trainer
from yadlt.core import UnsupervisedModel
from yadlt.utils import utilities


class DenoisingAutoencoder(UnsupervisedModel):
    """Implementation of Denoising Autoencoders using TensorFlow.

    The interface of the class is sklearn-like.
    """

    def __init__(
        self, n_components, name='dae',
        enc_act_func=tf.nn.tanh, dec_act_func=None, loss_func='mean_squared',
        num_epochs=10, batch_size=10, opt='sgd',
        learning_rate=0.01, momentum=0.5, corr_type='none', corr_frac=0.,
            regtype='none', regcoef=5e-4):
        """Constructor.

        :param n_components: number of hidden units
        :param enc_act_func: Activation function for the encoder.
            [tf.nn.tanh, tf.nn.sigmoid]
        :param dec_act_func: Activation function for the decoder.
            [tf.nn.tanh, tf.nn.sigmoid, None]
        :param corr_type: Type of input corruption.
            ["none", "masking", "salt_and_pepper"]
        :param corr_frac: Fraction of the input to corrupt.
        :param regcoef: Regularization parameter. If 0, no regularization.
        """
        UnsupervisedModel.__init__(self, name)

        self._initialize_training_parameters(
            loss_func=loss_func, learning_rate=learning_rate, opt=opt,
            num_epochs=num_epochs, batch_size=batch_size,
            momentum=momentum, regtype=regtype, regcoef=regcoef)

        self.loss = Loss(self.loss_func)
        self.trainer = Trainer(
            opt, learning_rate=learning_rate, momentum=momentum)

        self.n_components = n_components
        self.enc_act_func = enc_act_func
        self.dec_act_func = dec_act_func
        self.corr_type = corr_type
        self.corr_frac = corr_frac

        self.input_data_orig = None
        self.input_data = None

        self.W_ = None
        self.bh_ = None
        self.bv_ = None

    def _train_model(self, train_set, train_ref=None,
                     validation_set=None, validation_ref=None):
        """Train the model.

        :param train_set: training set
        :param train_ref: reference training data
        :param validation_set: validation set. optional, default None
        :param validation_ref: reference validation data
        :return: self
        """
        pbar = tqdm(range(self.num_epochs))
        for i in pbar:
            self._run_train_step(train_set)
            if validation_set is not None:
                feed = {self.input_data_orig: validation_set,
                        self.input_data: validation_set}
                err = self._run_validation_error_and_summaries(i, feed)
                pbar.set_description("Reconstruction loss: %s" % (err))

    def _run_train_step(self, train_set):
        """Run a training step.

        A training step is made by randomly corrupting the training set,
        randomly shuffling it,  divide it into batches and run the optimizer
        for each batch.
        :param train_set: training set
        :return: self
        """
        x_corrupted = utilities.corrupt_input(
            train_set, self.tf_session, self.corr_type, self.corr_frac)

        shuff = list(zip(train_set, x_corrupted))
        np.random.shuffle(shuff)

        batches = [_ for _ in utilities.gen_batches(shuff, self.batch_size)]

        for batch in batches:
            x_batch, x_corr_batch = zip(*batch)
            tr_feed = {self.input_data_orig: x_batch,
                       self.input_data: x_corr_batch}
            self.tf_session.run(self.train_step, feed_dict=tr_feed)

    def build_model(self, n_features, W_=None, bh_=None, bv_=None):
        """Create the computational graph.

        :param n_features: Number of features.
        :param regtype: regularization type
        :param W_: weight matrix np array
        :param bh_: hidden bias np array
        :param bv_: visible bias np array
        :return: self
        """
        self._create_placeholders(n_features)
        self._create_variables(n_features, W_, bh_, bv_)

        self._create_encode_layer()
        self._create_decode_layer()

        variables = [self.W_, self.bh_, self.bv_]
        regterm = Layers.regularization(variables, self.regtype, self.regcoef)

        self.cost = self.loss.compile(
            self.reconstruction, self.input_data_orig, regterm=regterm)
        self.train_step = self.trainer.compile(self.cost)

    def _create_placeholders(self, n_features):
        """Create the TensorFlow placeholders for the model.

        :return: self
        """
        self.input_data_orig = tf.placeholder(
            tf.float32, [None, n_features], name='x-input')
        self.input_data = tf.placeholder(
            tf.float32, [None, n_features], name='x-corr-input')
        # not used in this model, created just to comply
        # with unsupervised_model.py
        self.input_labels = tf.placeholder(tf.float32)
        self.keep_prob = tf.placeholder(tf.float32, name='keep-probs')

    def _create_variables(self, n_features, W_=None, bh_=None, bv_=None):
        """Create the TensorFlow variables for the model.

        :return: self
        """
        if W_:
            self.W_ = tf.Variable(W_, name='enc-w')
        else:
            self.W_ = tf.Variable(
                tf.truncated_normal(
                    shape=[n_features, self.n_components], stddev=0.1),
                name='enc-w')

        if bh_:
            self.bh_ = tf.Variable(bh_, name='hidden-bias')
        else:
            self.bh_ = tf.Variable(tf.constant(
                0.1, shape=[self.n_components]), name='hidden-bias')

        if bv_:
            self.bv_ = tf.Variable(bv_, name='visible-bias')
        else:
            self.bv_ = tf.Variable(tf.constant(
                0.1, shape=[n_features]), name='visible-bias')

    def _create_encode_layer(self):
        """Create the encoding layer of the network.

        :return: self
        """
        with tf.name_scope("encoder"):

            activation = tf.add(
                tf.matmul(self.input_data, self.W_),
                self.bh_
            )

            if self.enc_act_func:
                self.encode = self.enc_act_func(activation)
            else:
                self.encode = activation

    def _create_decode_layer(self):
        """Create the decoding layer of the network.

        :return: self
        """
        with tf.name_scope("decoder"):

            activation = tf.add(
                tf.matmul(self.encode, tf.transpose(self.W_)),
                self.bv_
            )

            if self.dec_act_func:
                self.reconstruction = self.dec_act_func(activation)
            else:
                self.reconstruction = activation

    def get_parameters(self, graph=None):
        """Return the model parameters in the form of numpy arrays.

        :param graph: tf graph object
        :return: model parameters
        """
        g = graph if graph is not None else self.tf_graph

        with g.as_default():
            with tf.Session() as self.tf_session:
                self.tf_saver.restore(self.tf_session, self.model_path)

                return {
                    'enc_w': self.W_.eval(),
                    'enc_b': self.bh_.eval(),
                    'dec_b': self.bv_.eval()
                }
