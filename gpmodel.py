''' Classes for doing Gaussian process models of proteins.'''

from collections import namedtuple
try:
    import cPickle as pickle
except:
    import pickle

import numpy as np
from scipy.optimize import minimize
from scipy import stats, integrate, linalg
import pandas as pd

import gpmean



class GPModel(object):

    """A Gaussian process model for proteins.

    Attributes:
        X_seqs (DataFrame): The sequences in the training set
        Y (Series): The outputs for the training set
        variances (Series): measurement variances for the training set
        normed_Y (Series): normalized outputs for the training set
        mean (float): mean of unnormed Ys
        std (float): standard deviation of unnormed Ys
        kern (GPKernel): a kernel for calculating covariances
        mean_func (GPMean): mean function
        hypers (namedtuple): the hyperparameters
        regr (Boolean): classification or regression
        _K (pd.DataFrame): Covariance matrix
        _Ky (np.ndarray): noisy covariance matrix [K+var_n*I]
        _L (np.ndarray): lower triangular Cholesky decomposition of Ky for
            regression models. Lower triangular Cholesky decomposition of
            (I + W_root*Ky*W_root.T) for classification models.
        _alpha (np.ndarray): L.T\(L\Y)
        ML (float): The negative log marginal likelihood
        log_p (float): the negative LOO log likelihood
        _ell (int): number of training samples
        _f_hat (Series): MAP values of the latent function for training set
        _W (np.ndarray): negative _hessian of the log likelihood
        _W_root (np.ndarray): Square root of W
        _grad (np.ndarray): gradient of the log logistic likelihood
    """

    def __init__ (self, kern, **kwargs):
        """ Create a new GPModel.

        Parameters:
            kern (GPKernel): kernel to use

        Optional keyword parameters:
            guesses (iterable): initial guesses for the
                hyperparameters.
                Default is [0.9 for _ in range(len(hypers))].
            objective (String): objective function to use in training
                model. Choices are 'log_ML' and 'LOO_log_p'.
                Classification must be trained on 'log_ML.' Default
                is 'log_ML'.
        """
        self.kern = kern
        self.guesses = None
        if 'objective' not in kwargs.keys():
            kwargs['objective'] = 'log_ML'
        if 'mean_func' not in kwargs.keys():
            self.mean_func = gpmean.GPMean()
        self.variances = None
        self._set_params(**kwargs)

    def _set_params(self, **kwargs):
        ''' Sets parameters for the model.

        This function can be used to set the value of any or all
        attributes for the model. However, it does not necessary
        update dependencies, so use with caution.

        Optional Keyword Parameters:
            X_seqs (DataFrame): The sequences in the training set
            Y (Series): The outputs for the training set
            normed_Y (Series): normalized outputs for the training set
            mean (float): mean of unnormed Ys
            std (float): standard deviation of unnormed Ys
            kern (GPKernel): a kernel for calculating covariances
            mean_func (GPMean): mean function
            hypers (namedtuple): the hyperparameters
            regr (Boolean): classification or regression
            _K (pdDataFrame): Covariance matrix
            _Ky (np.ndarray): noisy covariance matrix [K+var_n*I]
            _L (np.ndarray): lower triangular Cholesky decomposition of Ky for
                regression models. Lower triangular Cholesky decomposition of
                (I + W_root*Ky*W_root.T) for classification models.
            _alpha (np.ndarray): L.T\(L\Y)
            ML (float): The negative log marginal likelihood
            log_p (float): the negative LOO log likelihood
            _ell (int): number of training samples
            _f_hat (Series): MAP values of the latent function for training set
            _W (np.ndarray): negative _hessian of the log likelihood
            _W_root (np.ndarray): Square root of W
            _grad (np.ndarray): gradient of the log logistic likelihood
        '''
        for key, value in kwargs.iteritems():
            setattr(self, key, value)
        objective = kwargs.get('objective', None)
        hypers = kwargs.get('hypers', None)
        if objective is not None:
            if objective == 'log_ML':
                self.objective = self._log_ML
            elif objective == 'LOO_log_p':
                self.objective = self._LOO_log_p
            else:
                raise AttributeError (objective + ' is not a valid objective')
        if hypers is not None:
            if type(hypers) is not dict:
                if self.regr:
                    hypers_list = ['var_n'] + self.kern.hypers
                    Hypers = namedtuple('Hypers', hypers_list)
                else:
                    Hypers = namedtuple('Hypers', self.kern.hypers)
                self.hypers = Hypers._make(hypers)
            else:
                Hypers=namedtuple('Hypers', hypers.keys())
                self.hypers = Hypers(**hypers)


    def fit(self, X_seqs, Y, variances=None):
        ''' Fit the model to the given data.

        Set the hyperparameters by training on the given data.
        Update all dependent values.

        For regression models, measurement variances can be given, or
        a global measurement variance will be estimated.

        Parameters:
            X_seqs (pandas.DataFrame): Sequences in training set
            Y (pandas.Series): measurements in training set
            variances (pandas.Series): measurement variances. Index must
                match index for Y. Optional.
        '''
        self.X_seqs = X_seqs
        self.Y = Y
        self._ell = len(Y)
        self.kern.set_X(X_seqs)
        self.regr = not self.is_class()
        if self.regr:
            self.mean_func.fit(X_seqs, Y)
            self.Y = Y - self.mean_func.means
            self.mean, self.std, self.normed_Y = self._normalize (self.Y)
            if variances is not None:
                if not np.array_equal(variances.index, Y.index):
                    raise AttributeError('Indices do not match.')
                self.variances = variances / self.std**2
                n_guesses = len(self.kern.hypers)
            else:
                self.variances = None
                n_guesses = 1 + len(self.kern.hypers)
        else:
            n_guesses = len(self.kern.hypers)
            if self.objective == self._LOO_log_p:
                raise AttributeError\
                ('Classification models must be trained on marginal likelihood')
        if self.guesses == None:
            guesses = [0.9 for _ in range(n_guesses)]
        else:
            guesses = self.guesses
            if len(guesses) != n_guesses:
                raise AttributeError\
                ('Length of guesses does not match number of hyperparameters')

        bounds = [(1e-5,None) for _ in guesses]
        minimize_res = minimize(self.objective,
                                (guesses),
                                bounds=bounds,
                                method='L-BFGS-B')
        self._set_hypers(minimize_res['x'])

    def _set_hypers(self, hypers):
        ''' Set model.hypers and quantities used for making predictions.

        Parameters:
            hypers (iterable or dict)
        '''
        if type(hypers) is not dict:
            if self.regr and self.variances is None:
                hypers_list = ['var_n'] + self.kern.hypers
                Hypers = namedtuple('Hypers', hypers_list)
            else:
                Hypers = namedtuple('Hypers', self.kern.hypers)
            self.hypers = Hypers._make(hypers)
        else:
            Hypers=namedtuple('Hypers', hypers.keys())
            self.hypers = Hypers(**hypers)

        if self.regr:
            self._K, self._Ky = self._make_Ks(hypers)
            self._L = np.linalg.cholesky(self._Ky)
            self._alpha = np.linalg.lstsq(self._L.T,
                                         np.linalg.lstsq(self._L,
                                            np.matrix(self.normed_Y).T)[0])[0]
            self.ML = self._log_ML(self.hypers)
            self.log_p = self._LOO_log_p(self.hypers)
        else:
            self._f_hat = self._find_F(hypers=self.hypers)
            self._W = self._hess (self._f_hat)
            self._W_root = linalg.sqrtm(self._W)
            self._Ky = np.matrix(self.kern.make_K(hypers=self.hypers))
            self._L = np.linalg.cholesky (np.matrix(np.eye(self._ell))+self._W_root\
                                         *self._Ky*self._W_root)
            self._grad = np.matrix(np.diag(self._grad_log_logistic_likelihood\
                                          (self.Y,
                                           self._f_hat)))
            self.ML = self._log_ML(self.hypers)

    def _make_Ks(self, hypers):
        """ Make covariance matrix (K) and noisy covariance matrix (Ky)."""
        if len(hypers) == len(self.kern.hypers):
            if self.variances is None:
                raise AttributeError('No variances given.')
            K = self.kern.make_K(hypers=hypers)
            Ky = K + np.diag(self.variances)
        elif len(hypers) == len(self.kern.hypers) + 1:
            K = self.kern.make_K(hypers=hypers[1::])
            Ky = K + np.identity(len(K)) * hypers[0]
        else:
            raise AttributeError('len(hypers) does not match')
        return K, Ky

    def batch_UB_bandit(self, sequences, n=10, predictions=None):
        """ Use the batch UB bandit algorithm to select sequences.

        Select a sequence that maximizes the UB, add it to the observed
        sequences, and repeat.

        Parameters:
            sequences (pd.DataFrame): sequences to select from

        Optional keyword parameters:
            n (int): number to select. Default is 10.
            predictions (iterable): initial predictions. Default is None.

        Returns:
            selected_sequences (pd.DataFrame)
            inds (list)
        """
        observed_X = self.X_seqs
        observed_Y = self.normed_Y
        Ky = self._Ky
        selected = []
        print('Training kernel on new sequences...')
        self.kern.train(sequences)
        print('Making initial predictions...')
        if self.regr:
            h = self.hypers[1::]
        else:
            h = self.hypers
        # find all k*s
        k_stars = [self.kern.calc_kernel(ns, ns, hypers=h)
                   for ns in sequences.index]
        # find k vectors
        ks = [np.matrix([self.kern.calc_kernel(s, seq1, hypers=h)
                         for seq1 in self.X_seqs.index])
              for s in sequences.index]
        # calculate initial UBs if necessary
        if predictions is None:
            predictions = np.array([self._predict(k, k_star, unnorm=False)
                                    for k, k_star
                     in zip(ks, k_stars)])
        UBs = predictions[:,0] + np.sqrt(predictions[:,1]) * 2
        # initialize df, with same indices as sequences
        df = pd.DataFrame(predictions, index=sequences.index,
                          columns=['mean', 'var'])
        df['UB'] = UBs
        df['k_star'] = k_stars
        df['k'] = ks
        for i in range(n):
            print('\t%d' %i)
            # first selection
            id_max = df[['UB']].idxmax()
            print(max(df['UB']))
            selected.append(id_max.iloc[0])
            if i != n-1:
                observed_X = observed_X.append(sequences.loc[id_max])
                observed_Y = observed_Y.append(df.loc[id_max]['mean'])
                # update
                Ky = np.append(Ky, df.loc[id_max]['k'].values[0], axis=0)
                new_column = np.append(df.loc[id_max]['k'].values[0].flatten(),
                                np.array([df.loc[id_max]['k_star'].values
                                          + self.hypers.var_n]),
                               axis=1)
                Ky = np.append(Ky, new_column.T, axis=1)
                L = np.linalg.cholesky(Ky)
                alpha = np.linalg.lstsq(L.T,
                                        np.linalg.lstsq(L,
                                                np.matrix(observed_Y).T)[0])[0]
                df = df.drop(id_max, axis=0)
                ks = []
                for ind in df.index:
                    new_k = np.append(df.loc[ind]['k'],
                              np.array([[self.kern.calc_kernel(ind,
                                                    id_max.values[0],
                                                    hypers=h)]]),
                             axis=1)
                    ks.append(new_k)
                df['k'] = ks
                predictions = np.array([self._predict(k, k_star,
                                                      alpha=alpha,
                                                      L=L,
                                                      unnorm=False)
                                    for k, k_star
                     in zip(df['k'], df['k_star'])])
                UBs = predictions[:,0] + np.sqrt(predictions[:,1]) * 2
                df['UB'] = UBs
                df['mean'] = predictions[:,0]
                df['var'] = predictions[:,1]

        return sequences.loc[selected], selected

    def _normalize(self, data):
        """ Normalize the given data.

        Normalizes the elements in data by subtracting the mean and
        dividing by the standard deviation.

        Parameters:
            data (pd.Series)

        Returns:
            mean, standard_deviation, normed
        """
        m = data.mean()
        s = data.std()
        return m, s, (data-m) / s

    def unnormalize(self, normed):
        """ Inverse of _normalize, but works on single values or arrays.

        Parameters:
            normed

        Returns:
            normed*self.std * self.mean
        """
        return normed*self.std + self.mean

    def _predict (self, k, k_star, alpha=None, L=None, unnorm=True):
        """ Make prediction for one sequence.

        Predicts the mean and variance for one new sequence given its
        covariance vector.

        Uses Equations 2.23 and 2.24 of RW

        Parameters:
            k (np.matrix): k in equations 2.23 and 2.24
            k_star (float): k* in equation 2.24

        Returns:
            res (tuple): (E,v) as floats for regression, pi_star for
                classification
        """
        if self.regr:
            if alpha is None:
                alpha = self._alpha
            if L is None:
                L = self._L
            E = np.dot(k,alpha)
            v = np.linalg.lstsq(L,k.T)[0]
            var = k_star - np.dot(v.T, v)
            if unnorm:
                E = self.unnormalize(E)
                var *= self.std**2
            return (E.item(),var.item())
        else:
            f_bar = np.dot(k, self._grad.T)
            v = np.linalg.lstsq(self._L, np.dot(self._W_root, k.T))[0]
            var = k_star - np.dot(v.T, v)
            i = 10
            pi_star = integrate.quad(self._p_integral,
                                     -i*var+f_bar,
                                     f_bar+i*var,
                                     args=(f_bar.item(), var.item()))[0]
            return (pi_star, f_bar.item(), var.item())

    def predicts (self, new_seqs, delete=True):
        """Make predictions for each sequence in new_seqs.

        Uses Equations 2.23 and 2.24 of RW
        Parameters:
            new_seqs (DataFrame): sequences to predict.
                They must have unique indices.

         Returns:
            predictions (list): (E,v) as floats
        """
        predictions = []
        self.kern.train(new_seqs)
        if self.regr:
            h = self.hypers[1::]
        else:
            h = self.hypers
        for ns in new_seqs.index:
            k = np.array([self.kern.calc_kernel(ns, seq1,
                                                hypers=h) \
                           for seq1 in self.X_seqs.index])
            k = k.reshape(1, len(k))
            k_star = self.kern.calc_kernel(ns, ns,
                                           hypers=h)
            predictions.append(self._predict(k, k_star))
        if delete:
            inds = list(set(new_seqs.index) - set(self.X_seqs.index))
            self.kern.delete(new_seqs.loc[inds, :])
        if self.regr:
            means = self.mean_func.mean(new_seqs)
            predictions = [(m+p, v)
                           for p, (m, v) in zip(means, predictions)]
        return predictions

    def _p_integral (self, z, mean, variance):
        ''' Equation 3.25 from RW with a sigmoid likelihood.

        Equation to integrate when calculating pi_star for classification.

        Parameters:
            z (float): value at which to evaluate the function.
            mean (float): mean of the Gaussian
            variance (float): variance of the Gaussian

        Returns:
            res (float)
        '''
        try:
            first = 1./(1+np.exp(-z))
        except OverflowError:
            first = 0.
        try:
            second = 1/np.sqrt(2*np.pi*variance)
        except:
            second = -1
        third = np.exp(-(z-mean)**2/(2*variance))
        return first*second*third

    def _log_ML (self, hypers):
        """ Returns the negative log marginal likelihood for the model.

        Uses RW Equation 5.8 for regression models and Equation 3.32 for
        classification models.

        Parameters:
            hypers (iterable): the hyperparameters

        Returns:
            log_ML (float)
        """
        if self.regr:
            Y = self.normed_Y.values.reshape(1, len(self.normed_Y))
            K, Ky = self._make_Ks(hypers)
            L = np.linalg.cholesky (Ky)
            alpha = np.linalg.lstsq(L.T, np.linalg.lstsq
                                    (L, Y.T)[0])[0]
            first = 0.5 * np.dot(Y, alpha)
            second = np.sum(np.log(np.diag(L)))
            third = len(K)/2.*np.log(2*np.pi)
            ML = (first+second+third).item()
            return ML
        else:
            f_hat = self._find_F(hypers=hypers) # use Algorithm 3.1 to find mode
            ML = self._logq(f_hat, hypers=hypers)
            return ML.item()

    def is_class (self):
        '''True if Y only contains values 1 and -1, otherwise False'''
        return all (y in [-1,1] for y in self.Y)

    def _logistic_likelihood (self, Y, F):
        ''' Calculate logistic likelihood.

        Calculates the logistic probability of the outcome y given
        the latent  variable f according to Equation 3.2 in RW.

        Parameters:
            Y (float or np.ndarray): +/- 1
            F (float or np.ndarray): value of latent function

        Returns:
            float
        '''
        if isinstance(Y, np.ndarray):
            if not ((Y==1).astype(int) + (Y==-1).astype(int)).all():
                raise RuntimeError ('All values in Y must be -1 or 1')
        else:
            if int(Y) not in [1, -1]:
                raise RuntimeError('Y must be -1 or 1')
        return 1./(1+np.exp(-Y*F))

    def _log_logistic_likelihood (self,Y, F):
        """ Calculate the log logistic likelihood.

        Calculates the log logistic likelihood of the outcomes Y
        given the latent variables F. log[p(Y|f)]. Uses Equation
        3.15 of RW.

        Parameters:
            Y (Series): outputs, +/-1
            F (Series): values for the latent function

        Returns:
            lll (float): log logistic likelihood
        """
        if len(Y) != len(F):
            raise RuntimeError ('Y and F must be the same length')
        lll = np.sum(np.log(self._logistic_likelihood(Y.values,F.values)))
        return lll

    def _grad_log_logistic_likelihood (self,Y,F):
        """ Calculate the gradient of the log logistic likelihood.

        Calculates the gradient of the logistic likelihood of the
        outcomes Y given the latent variables F.
        Uses Equation 3.15 of RW.

        Parameters:
            Y (Series): outputs, +/-1
            F (Series): values for the latent function

        Returns:
            glll (np.ndarray): diagonal matrix containing the
                gradient of the log likelihood
        """
        Y = Y.values
        F = F.values
        glll = (Y + 1) / 2.0 -  self._logistic_likelihood(1.0, F)
        return np.diag(glll)

    def _hess (self,F):
        """ Calculate the negative _hessian of the logistic likelihod.

        Calculates the negative hessian of the logistic likelihood
        according to Equation 3.15 of RW.

        Parameters:
            F (Series): values for the latent function

        Returns:
            W (np.matrix): diagonal negative hessian of the log
                likelihood matrix
        """
        F = F.values
        pi = self._logistic_likelihood(1.0, F)
        W =  pi * (1 - pi)
        return np.diag(W)

    def _find_F (self, hypers, guess=None, threshold=.0001, evals=1000):
        """Calculates f_hat according to Algorithm 3.1 in RW.

        Returns:
            f_hat (pd.Series)
        """
        ell = len(self.Y)
        if guess == None:
            f_hat = pd.Series(np.zeros(ell))
        elif len(guess) == l:
            f_hat = guess
        else:
            raise ValueError('Initial guess must have same dimensions as Y')
        K = self.kern.make_K(hypers=hypers)
        n_below = 0
        for i in range(evals):
            # find new f_hat
            W = self._hess(f_hat)
            W_root = linalg.sqrtm(W)
            trip_dot = (W_root.dot(K)).dot(W_root)
            L = np.linalg.cholesky(np.eye(ell) + trip_dot)
            b =  W.dot(f_hat.T)
            b += np.diag(self._grad_log_logistic_likelihood(self.Y, f_hat)).T
            b = b.reshape(len(b), 1)
            trip_dot_lstsq = np.linalg.lstsq(L, (W_root.dot(K)).dot(b))[0]
            a = b - W_root.dot(np.linalg.lstsq(L.T, trip_dot_lstsq)[0])
            f_new = K.dot(a)
            f_new = f_new.reshape((len(f_new), ))
            sq_error = np.sum((f_hat.values - f_new) ** 2)
            f_new = pd.Series(f_new)
            if sq_error / np.sum(f_new) < threshold:
                n_below += 1
            else:
                n_below = 0
            if n_below > 9:
                f_new.index = self.X_seqs.index
                return f_new
            f_hat = f_new
        raise RuntimeError('Maximum evaluations reached without convergence.')

    def _logq(self, F, hypers):
        ''' Calculate negative log marginal likelihood.

        Finds the negative log marginal likelihood for Laplace's
        approximation Equation 5.20 or 3.12 from RW, as described
        in Algorithm 5.1

        Parameters:
            var_p (float)
            F (Series): values for the latent function

        Returns:
            _logq (float)
        '''
        ell = self._ell
        K = self.kern.make_K(hypers=hypers)
        W = self._hess (F)
        W_root = linalg.sqrtm(W)
        F_mat = F.values.reshape(len(F), 1)
        trip_dot = (W_root.dot(K)).dot(W_root)
        L = np.linalg.cholesky(np.eye(ell) + trip_dot)
        b = W.dot(F_mat) + np.diag(self._grad_log_logistic_likelihood(self.Y, F)).reshape(len(F), 1)
        b = b.reshape(len(b), 1)
        trip_dot_lstsq = np.linalg.lstsq(L, (W_root.dot(K)).dot(b))[0]
        a = b - W_root.dot(np.linalg.lstsq(L.T, trip_dot_lstsq)[0])
        _logq = 0.5 * np.dot(a.T, F_mat) - self._log_logistic_likelihood(self.Y, F) \
        + np.sum(np.log(np.diag(L)))
        return _logq


    def _LOO_log_p (self, hypers):
        """ Calculates the negative LOO log probability.

        For now, only for regression
        Equation 5.10 and 5.11 from RW
        Parameters:
            variances (iterable)
        Returns:
            log_p
        """
        LOO = self.LOO_res(hypers)
        vs = LOO['v']
        mus = LOO['mu']
        log_ps = -0.5*np.log(vs) - \
        (self.normed_Y-mus)**2 / 2 / vs - 0.5*np.log(2*np.pi)
        return_me = -sum (log_ps)
        return return_me

    def LOO_res (self, hypers, add_mean=False, unnorm=False):
        """ Calculates LOO regression predictions.

        Calculates the LOO predictions according to Equation 5.12 from RW.

        Parameters:
            hypers (iterable)
            add_mean (Boolean): whether or not to add in the mean function.
                Default is False.
            unnormalize (Boolean): whether or not to unnormalize.
                Default is False unless the mean is added back, in which
                case always True.
        Returns:
            res (pandas.DataFrame): columns are 'mu' and 'v'
        """
        K, Ky = self._make_Ks(hypers)
        K_inv = np.linalg.inv(Ky)
        Y = self.normed_Y.values.reshape(len(self.normed_Y), 1)
        mus = np.diag(Y - np.dot(K_inv, Y) / K_inv)
        vs = np.diag(1 / K_inv)
        if add_mean or unnorm:
            mus = self.unnormalize(mus)
            vs = np.array(vs).copy()
            vs *= self.std**2
        if add_mean:
            mus += self.mean_func.means
        return pd.DataFrame(zip(mus, vs), index=self.normed_Y.index,
                           columns=['mu', 'v'])

    def score (self, X, Y, *args):
        ''' Score the model on the given points.

        Predicts Y for the sequences in X, then scores the predictions.

        Parameters:
            X (pandas.DataFrame)
            Y (pandas.Series)
            type (string): always AUC for classification. 'kendalltau',
                'R2', or 'R' for regression. Default is 'kendalltau.'

        Returns:
            res: If one score, result is a float. If multiple, result is a dict.
        '''
        # Check that X and Y have the same indices
        if not (set(X.index) == set(Y.index) and len(X) == len(Y)):
            raise ValueError\
            ('X and Y must be the same length and have the same indices.')
        # Make predictions
        predicted = self.predicts(X)

        # for classification, return the ROC AUC
        if not self.regr:
            from sklearn.metrics import roc_auc_score
            return roc_auc_score(Y, predicted)

        else:
            pred_Y = [y for (y,v) in predicted]

            # if nothing specified, return Kendall's Tau
            if not args:
                r1 = stats.rankdata(Y)
                r2 = stats.rankdata(pred_Y)
                return stats.kendalltau(r1, r2).correlation

            scores = {}
            for t in args:
                if t == 'kendalltau':
                    r1 = stats.rankdata(Y)
                    r2 = stats.rankdata(pred_Y)
                    scores[t] = stats.kendalltau(r1, r2).correlation
                elif t == 'R2':
                    from sklearn.metrics import r2_score
                    scores[t] = r2_score(Y, pred_Y)
                elif t =='R':
                    scores[t] = np.corrcoef(Y, pred_Y)[0,1]
                else:
                    raise ValueError ('Invalid metric.')
            if len (scores.keys()) == 1:
                return scores[scores.keys()[0]]
            else:
                return scores

    @classmethod
    def load(cls, model):
        ''' Load a saved model.

        Use cPickle to load the saved model.

        Parameters:
            model (string): path to saved model
        '''
        with open(model,'r') as m_file:
            attributes = pickle.load(m_file)
        model = GPModel(attributes['kern'])
        del attributes['kern']
        model._set_params(**attributes)
        return model

    def dump(self, f):
        ''' Save the model.

        Use cPickle to save a dict containing the model's
        attributes.

        Parameters:
            f (string): path to where model should be saved
        '''
        save_me = {k:self.__dict__[k] for k in self.__dict__.keys()}
        if self.objective == self._log_ML:
            save_me['objective'] = 'log_ML'
        else:
            save_me['objective'] = 'LOO_log_p'
        save_me['guesses'] = self.guesses
        try:
            names = self.hypers._fields
            hypers = {n:h for n,h in zip(names, self.hypers)}
            save_me['hypers'] = hypers
        except AttributeError:
            pass
        with open(f, 'wb') as f:
            pickle.dump(save_me, f)


