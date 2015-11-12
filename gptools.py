import matplotlib.pyplot as plt
import gpmodel
import math
import numpy as np
import gpkernel
import pandas as pd
from sklearn import metrics
from sys import exit
import scipy

import seaborn as sns

rc = {'lines.linewidth': 3,
      'axes.labelsize': 18,
      'axes.titlesize': 18,
      'axes.facecolor': 'DFDFE5'}
sns.set_context('notebook', rc=rc)
sns.set_style('darkgrid', rc=rc)

######################################################################
# Here are some plotting tools that are generally useful
######################################################################

def plot_predictions (real_Ys, predicted_Ys,
                      stds=None, file_name=None, title='',label='', line=True):
    if stds is None:
        plt.plot (real_Ys, predicted_Ys, 'g.')
    else:
        plt.errorbar (real_Ys, predicted_Ys, yerr = [stds, stds], fmt = 'g.')
    small = min(set(real_Ys) | set(predicted_Ys))*1.1
    if small == 0:
        small = real_Ys.mean()/10.0
    large = max(set(real_Ys) | set(predicted_Ys))*1.1
    if line:
        plt.plot ([small, large], [small, large], 'b--')
    plt.xlabel ('Actual ' + label)
    plt.ylabel ('Predicted ' + label)
    plt.title (title)
    #plt.xlim (small, large)
    if small < 0:
        left = small*0.8
    else:
        left = small*1.2
    if large < 0:
        right = large*1.3
    else:
        right = large*0.7
    plt.text(left, right, 'R = %.3f' %np.corrcoef(real_Ys, predicted_Ys)[0,1])
    if not file_name is None:
        plt.savefig (file_name)

def plot_ROC (real_Ys, pis, file_name=None,title=''):
    fpr, tpr, _ = metrics.roc_curve(real_Ys, pis)
    plt.plot (fpr,tpr,'.-')
    plt.xlim([-.1,1.1])
    plt.ylim([-.1,1.1])
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    auc = metrics.auc(fpr,tpr)
    plt.title(title+' auc = %.4f' %auc)
    if not file_name is None:
        plt.savefig (file_name)

def plot_LOO(Xs, Ys, kernel, save_as=None, lab=''):
    std = []
    predicted_Ys = []
    count = 0
    for i in Xs.index:
        train_inds = list(set(Xs.index) - set(i))
        train_Xs = Xs.loc[train_inds]
        train_Ys = Ys.loc[train_inds]
        verify = Xs.loc[[i]]
        print 'Building model for ' + str(i)
        model = gpmodel.GPModel(train_Xs,train_Ys, kernel, guesses=[0.74,.0002684], train=(count<1))
        count += 1
        print 'Making prediction for ' + str(i)
        predicted = model.predicts(verify, delete=False)
        if model.is_class():
            E = predicted[0]
        else:
            try:
                [(E,v)] = predicted
            except ValueError:
                print 'ValueError', i, predicted
            std.append(math.pow(v,0.5))
        predicted_Ys.append (E)
    plot_predictions (Ys.tolist(),
                      predicted_Ys,
                      stds=None,
                      label=lab,
                      line=model.regr,
                      file_name=save_as)
    return predicted_Ys,std

def log_marginal_likelihood (variances, model):
    """ Returns the negative log marginal likelihood.

        Parameters:
            model: a GPmodel regression model
            variances (iterable): var_n and var_p

        Uses RW Equation 5.8
    """
    if model.regr:
        Y_mat = np.matrix(model.normed_Y)
        var_n,var_p = variances
        K_mat = np.matrix (model.K)
        Ky = K_mat*var_p+np.identity(len(K_mat))*var_n
        L = np.linalg.cholesky (Ky)
        alpha = np.linalg.lstsq(L.T,np.linalg.lstsq (L, np.matrix(Y_mat).T)[0])[0]
        first = -0.5*Y_mat*alpha
        second = -sum([math.log(l) for l in np.diag(L)])
        third = -len(K_mat)/2.*math.log(2*math.pi)
        ML = (first+second+third).item()
        return (first, second, third, ML)
    else:
        Y_mat = np.matrix(model.Y)
        vp = variances
        f_hat = model.find_F(var_p=vp)
        K_mat = vp*np.matrix (model.K)
        W = model.hess (f_hat)
        W_root = scipy.linalg.sqrtm(W)
        F_mat = np.matrix (f_hat)
        ell = len(model.Y)
        L = np.linalg.cholesky (np.matrix(np.eye(ell))+W_root*K_mat*W_root)
        b = W*F_mat.T + \
        np.matrix(np.diag(model.grad_log_logistic_likelihood (model.Y,f_hat))).T
        a = b - W_root*np.linalg.lstsq(L.T,np.linalg.lstsq(L,W_root*K_mat*b)[0])[0]
        fit = -0.5*a.T*F_mat.T + model.log_logistic_likelihood(model.Y, f_hat)
        complexity = -sum(np.log(np.diag(L)))
        return (fit, complexity, fit+complexity)


def plot_ML_contour (model, ranges, save_as=None, lab='', n=100, n_levels=10):
    """
    Make a plot of how ML varies with the hyperparameters for a given model
    """
    if model.regr:
        vns = np.linspace(ranges[0][0], ranges[0][1], n)
        vps = np.linspace(ranges[1][0], ranges[1][1], n)
        nn,pp = np.meshgrid(vns, vps)
        log_ML = np.empty_like(nn)
        for j in range(len(vns)):
            for i in range(len(vps)):
                log_ML[j,i] = -model.log_ML((nn[i,j],pp[i,j]))
        levels = np.linspace(log_ML.min(), log_ML.max(), n_levels)
        print levels
        cs = plt.contour(nn, pp, log_ML, alpha=0.7,levels=levels)

        plt.clabel(cs)
        plt.xlabel(r'$\sigma_n^2$')
        plt.ylabel(r'$\sigma_p^2$')
        plt.title(lab)
        return log_ML

    else:
        vps = np.linspace(ranges[0], ranges[1], n)
        log_ML = np.empty_like(vps)
        for i,p in enumerate(vps):
            log_ML[i] = -model.logistic_log_ML([p])

        plt.plot(vps, log_ML,'.-')
        plt.xlabel(r'$\sigma_p^2$')
        plt.ylabel('log marginal likelihood')
        plt.title(lab)
        return log_ML

def plot_ML_parts (model, ranges, lab='', n=100, plots=['log_ML','fit','complexity']):
    if model.regr:
        if len(ranges[0]) == 1:
            indpt = 'var_p**2'
            held = 'var_n**2'
            cons = ranges[0][0]
            lower = ranges[1][0]
            upper = ranges[1][1]
        elif len(ranges[1]) == 1:
            indpt = 'var_n**2'
            held = 'var_p**2'
            cons = ranges[1][0]
            lower = ranges[0][0]
            upper = ranges[0][1]
        varied = np.linspace(lower, upper, n)
        ML = np.empty_like(varied)
        fit = np.empty_like(varied)
        complexity = np.empty_like(varied)
        norm = np.empty_like(varied)
        for i,v in enumerate(varied):
            if indpt == 'var_p**2':
                fit[i],complexity[i],norm[i],ML[i] = log_marginal_likelihood((cons,v), model)
            else:
                fit[i],complexity[i],norm[i],ML[i] = log_marginal_likelihood((v,cons), model)
        #log_ML -= log_ML.max()
    else:
        indpt = 'var_p**2'
        varied = np.linspace(ranges[0], ranges[1], n)
        ML = np.empty_like(varied)
        fit = np.empty_like(varied)
        norm = np.empty_like(varied)
        complexity = np.empty_like(varied)
        for i,v in enumerate(varied):
            fit[i], complexity[i], ML[i] = log_marginal_likelihood(v, model)


    plot_dict = {'log_ML':ML, 'fit':fit, 'complexity':complexity, 'norm':norm}
    for pl in plots:
        plt.plot(varied, plot_dict[pl])
    plt.legend(plots)
    plt.xlabel(indpt)
    if model.regr:
        plt.title(lab + ' ' + held + ' = %f' %cons)
    else:
        plt.title(lab)
    return (fit, complexity, ML)

if __name__ == "__main__":
    pass



