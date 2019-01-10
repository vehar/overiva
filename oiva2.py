'''
Blind Source Separation using Independent Vector Analysis with Auxiliary Function

2018 (c) Robin Scheibler, MIT License
'''
import numpy as np

from pyroomacoustics.bss import projection_back

def oiva2(X, n_src=None, n_iter=20, proj_back=True, W0=None,
        f_contrast=None, f_contrast_args=[],
        return_filters=False, callback=None):

    '''
    Implementation of overdetermined IVA algorithm for BSS

    Parameters
    ----------
    X: ndarray (nframes, nfrequencies, nchannels)
        STFT representation of the signal
    n_src: int, optional
        The number of sources or independent components
    n_iter: int, optional
        The number of iterations (default 20)
    proj_back: bool, optional
        Scaling on first mic by back projection (default True)
    W0: ndarray (nfrequencies, nchannels, nchannels), optional
        Initial value for demixing matrix
    f_contrast: dict of functions
        A dictionary with two elements 'f' and 'df' containing the contrast
        function taking 3 arguments This should be a ufunc acting element-wise
        on any array
    return_filters: bool
        If true, the function will return the demixing matrix too
    callback: func
        A callback function called every 10 iterations, allows to monitor convergence

    Returns
    -------
    Returns an (nframes, nfrequencies, nsources) array. Also returns
    the demixing matrix (nfrequencies, nchannels, nsources)
    if ``return_values`` keyword is True.
    '''

    n_frames, n_freq, n_chan = X.shape

    # default to determined case
    if n_src is None:
        n_src = X.shape[2]

    # covariance matrix of input signal (n_freq, n_chan, n_chan)
    Cx = np.mean(X[:,:,:,None] * np.conj(X[:,:,None,:]), axis=0)

    # initialize the demixing matrices
    if W0 is None:

        W = np.zeros((n_freq, n_chan, n_src), dtype=X.dtype)
        A = np.zeros((n_freq, n_chan, n_src), dtype=X.dtype)

        # initialize A and W
        v,w = np.linalg.eig(Cx)
        for f in range(n_freq):
            ind = np.argsort(v[f])[-n_src:]
            eigval = v[f][ind]
            eigvec = np.conj(w[f][:,ind])
            A[f,:,:] = eigvec * eigval[None,:]
            W[f,:,:] = eigvec / eigval[None,:]

            W[f,:n_src,:] = np.eye(n_src)
            A[f,:n_src,:] = np.eye(n_src)


    else:
        assert W0.shape == (n_chan, n_src), 'Mismatch in size of initial demixing matrix'
        W = W0.copy()
        A = np.zeros((n_freq, n_chan, n_src), dtype=X.dtype)

    # keep L^{-1} as a view on the top part of the mixing matrix
    L_inv = A[:,:n_src,:]

    # last part of the demixing matrix
    J = np.zeros((n_freq, n_src, n_chan - n_src), dtype=X.dtype)
    J[:,:,:] = np.linalg.solve(np.conj(L_inv).swapaxes(1,2), np.conj(A[:,n_src:,:]).swapaxes(1,2))

    # shape == (n_freq, n_src, n_src)
    C11 = 0.5 * np.mean(X[:,:,:n_src,None] * np.conj(X[:,:,None,:n_src]), axis=0)
    # shape == (n_freq, n_src, n_chan - n_src)
    C12 = 0.5 * np.mean(X[:,:,:n_src,None] * np.conj(X[:,:,None,n_src:]), axis=0)

    # other variables
    I = np.eye(n_src,n_src)
    Y = np.zeros((n_frames, n_freq, n_src), dtype=X.dtype)
    V = np.zeros((n_freq, n_src, n_chan, n_chan), dtype=X.dtype)
    r = np.zeros((n_frames, n_src))

    # Compute the demixed output
    def demix(Y, X, W):
        for f in range(n_freq):
            Y[:,f,:] = np.dot(X[:,f,:], np.conj(W[f,:,:]))

    def update_L(L, W, J):

        B = W[:,:n_src,:]
        C = W[:,n_src:,:]

        tmp = np.conj(B + np.matmul(J, C)).swapaxes(1,2)
        L[:,:,:] = np.linalg.inv(tmp)

    def cost_func(Y, r, A):

        # need to compute L from A
        L_inv = A[:,:n_src,:]
        L = np.linalg.solve(L_inv, np.tile(I, (n_freq,1,1)))

        # now compute log det
        c1 = -2 * n_frames * np.sum(np.linalg.slogdet(L)[1])

        # now compute the log of activations
        c2 = n_freq * np.sum(np.log(r)) + n_freq

        return c1 + c2


    the_cost = []

    import matplotlib.pyplot as plt

    for epoch in range(n_iter):

        demix(Y, X, W)

        if callback is not None and epoch % 10 == 0:
            if proj_back:
                z = projection_back(Y, X[:,:,0])
                callback(Y * np.conj(z[None,:,:]))
            else:
                callback(Y)

        # shape: (n_frames, n_src)
        r[:,:] = np.mean(np.abs(Y * np.conj(Y)), axis=1)

        if epoch % 3 == 0:
            the_cost.append(cost_func(Y, r, A))
            print('{}: {}'.format(epoch, the_cost[-1]))

        # set the scale of r
        '''
        gamma = r.mean(axis=0)
        r /= gamma[None,:]
        Y /= np.sqrt(gamma[None,None,:])
        W /= np.sqrt(gamma[None,None,:])
        A *= np.sqrt(gamma[None,None,:])
        '''

        '''
        eps = 1e-5
        r[r < eps] = eps
        '''

        '''
        if epoch % 10 == 0:
            plt.figure()
            plt.plot(r)
            plt.title('r {}'.format(epoch))
        '''

        if epoch % 3 == 0:
            after_scaling = cost_func(Y, r, A)
            print('  after scaling: {}'.format(after_scaling))

        # Compute Auxiliary Variable
        np.mean(
                (0.5 * X[:,:,None,:,None] / r[:,None,:,None,None])
                * np.conj(X[:,:,None,None,:]),
                axis=0,
                out=V,
                )

        # Update now the demixing matrix
        for s in range(n_src):
            W[:,:,s] = np.linalg.solve(V[:,s,:,:], A[:,:,s])

            # normalize
            P1 = np.conj(W[:,:,s])
            P2 = np.sum(V[:,s,:,:] * W[:,None,:,s], axis=-1)
            W[:,:,s] /= np.sqrt(
                    np.sum(P1 * P2, axis=1)
                    )[:,None]

        
            update_L(L_inv, W, J)

            # Update the noise beamforming matrix
            C = W[:,n_src:,:].swapaxes(1,2)
            J[:,:,:] = np.linalg.solve(C11, np.matmul(L_inv, np.conj(C)) + C12)

            update_L(L_inv, W, J)

            # update the lower part of the mixing model
            A[:,n_src:,:] = np.matmul(np.conj(J).swapaxes(1,2), L_inv)

        if epoch % 3 == 0:
            wha = np.matmul(np.conj(W.swapaxes(-2,-1)), A)
            const_goodness = np.linalg.norm(wha - np.eye(n_src)[None,:,:], axis=(1,2))
            num = len(np.where(const_goodness > 1e-1)[0])
            print('Const: max err: {}, numbers > 1e-1: {}'.format(np.max(const_goodness), num))

    demix(Y, X, W)

    # shape: (n_frames, n_src)
    r[:,:] = np.mean(np.abs(Y * np.conj(Y)), axis=1)

    if epoch % 3 == 0:
        the_cost.append(cost_func(Y, r, A))

    plt.figure()
    plt.plot(np.arange(len(the_cost)) * 3, the_cost)
    plt.title('The cost function')
    plt.xlabel('Number of iterations')
    plt.ylabel('Neg. log-likelihood')

    if proj_back:
        print('proj back!')
        z = projection_back(Y, X[:,:,0])
        Y *= np.conj(z[None,:,:])

    if return_filters:
        return Y, W, A
    else:
        return Y
