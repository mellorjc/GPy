import numpy as np
import unittest
import GPy
from ..models import GradientChecker
import functools
import inspect
from ..likelihoods import link_functions
from ..core.parameterization import Param
from functools import partial
#np.random.seed(300)
#np.random.seed(7)

def dparam_partial(inst_func, *args):
    """
    If we have a instance method that needs to be called but that doesn't
    take the parameter we wish to change to checkgrad, then this function
    will change the variable using set params.

    inst_func: should be a instance function of an object that we would like
                to change
    param: the param that will be given to set_params
    args: anything else that needs to be given to the function (for example
          the f or Y that are being used in the function whilst we tweak the
          param
    """
    def param_func(param_val, param_name, inst_func, args):
        #inst_func.im_self._set_params(param)
        #inst_func.im_self.add_parameter(Param(param_name, param_val))
        inst_func.im_self[param_name] = param_val
        return inst_func(*args)
    return functools.partial(param_func, inst_func=inst_func, args=args)

def dparam_checkgrad(func, dfunc, params, params_names, args, constraints=None, randomize=False, verbose=False):
    """
    checkgrad expects a f: R^N -> R^1 and df: R^N -> R^N
    However if we are holding other parameters fixed and moving something else
    We need to check the gradient of each of the fixed parameters
    (f and y for example) seperately,  whilst moving another parameter.
    Otherwise f: gives back R^N and
              df: gives back R^NxM where M is
    The number of parameters and N is the number of data
    Need to take a slice out from f and a slice out of df
    """
    print "\n{} likelihood: {} vs {}".format(func.im_self.__class__.__name__,
                                           func.__name__, dfunc.__name__)
    partial_f = dparam_partial(func, *args)
    partial_df = dparam_partial(dfunc, *args)
    gradchecking = True
    zipped_params = zip(params, params_names)
    for param_ind, (param_val, param_name) in enumerate(zipped_params):
        #Check one parameter at a time, make sure it is 2d (as some gradients only return arrays) then strip out the parameter
        fnum = np.atleast_2d(partial_f(param_val, param_name))[:, param_ind].shape[0]
        dfnum = np.atleast_2d(partial_df(param_val, param_name))[:, param_ind].shape[0]
        for fixed_val in range(dfnum):
            #dlik and dlik_dvar gives back 1 value for each
            f_ind = min(fnum, fixed_val+1) - 1
            print "fnum: {} dfnum: {} f_ind: {} fixed_val: {}".format(fnum, dfnum, f_ind, fixed_val)
            #Make grad checker with this param moving, note that set_params is NOT being called
            #The parameter is being set directly with __setattr__
            #Check only the parameter and function value we wish to check at a time
            grad = GradientChecker(lambda p_val: np.atleast_2d(partial_f(p_val, param_name))[f_ind, param_ind],
                                   lambda p_val: np.atleast_2d(partial_df(p_val, param_name))[fixed_val, param_ind],
                                   param_val, [param_name])

            if constraints is not None:
                for constrain_param, constraint in constraints:
                    if grad.grep_param_names(constrain_param):
                        constraint(constrain_param, grad)
                    else:
                        print "parameter didn't exist"
                    print constrain_param, " ", constraint
            if randomize:
                grad.randomize()
            if verbose:
                print grad
                grad.checkgrad(verbose=1)
            if not grad.checkgrad():
                gradchecking = False

    return gradchecking


from nose.tools import with_setup
class TestNoiseModels(object):
    """
    Generic model checker
    """
    def setUp(self):
        self.N = 15
        self.D = 3
        self.X = np.random.rand(self.N, self.D)*10

        self.real_std = 0.1
        noise = np.random.randn(*self.X[:, 0].shape)*self.real_std
        self.Y = (np.sin(self.X[:, 0]*2*np.pi) + noise)[:, None]
        self.f = np.random.rand(self.N, 1)
        self.binary_Y = np.asarray(np.random.rand(self.N) > 0.5, dtype=np.int)[:, None]
        self.positive_Y = np.exp(self.Y.copy())
        tmp = np.round(self.X[:, 0]*3-3)[:, None] + np.random.randint(0,3, self.X.shape[0])[:, None]
        self.integer_Y = np.where(tmp > 0, tmp, 0)

        self.var = 0.2

        self.var = np.random.rand(1)

        #Make a bigger step as lower bound can be quite curved
        self.step = 1e-4

    def tearDown(self):
        self.Y = None
        self.f = None
        self.X = None

    def test_noise_models(self):
        self.setUp()

        ####################################################
        # Constraint wrappers so we can just list them off #
        ####################################################
        def constrain_fixed(regex, model):
            model[regex].constrain_fixed()

        def constrain_negative(regex, model):
            model[regex].constrain_negative()

        def constrain_positive(regex, model):
            model[regex].constrain_positive()

        def constrain_bounded(regex, model, lower, upper):
            """
            Used like: partial(constrain_bounded, lower=0, upper=1)
            """
            model[regex].constrain_bounded(lower, upper)

        """
        Dictionary where we nest models we would like to check
            Name: {
                "model": model_instance,
                "grad_params": {
                    "names": [names_of_params_we_want, to_grad_check],
                    "vals": [values_of_params, to_start_at],
                    "constrain": [constraint_wrappers, listed_here]
                    },
                "laplace": boolean_of_whether_model_should_work_for_laplace,
                "ep": boolean_of_whether_model_should_work_for_laplace,
                "link_f_constraints": [constraint_wrappers, listed_here]
                }
        """
        noise_models = {"Student_t_default": {
                            "model": GPy.likelihoods.StudentT(deg_free=5, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [self.var],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                #"constraints": [("t_noise", constrain_positive), ("deg_free", partial(constrain_fixed, value=5))]
                                },
                            "laplace": True
                            },
                        "Student_t_1_var": {
                            "model": GPy.likelihoods.StudentT(deg_free=5, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [1.0],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                },
                            "laplace": True
                            },
                        "Student_t_small_deg_free": {
                            "model": GPy.likelihoods.StudentT(deg_free=1.5, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [self.var],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                },
                            "laplace": True
                            },
                        "Student_t_small_var": {
                            "model": GPy.likelihoods.StudentT(deg_free=5, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [0.0001],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                },
                            "laplace": True
                            },
                        "Student_t_large_var": {
                            "model": GPy.likelihoods.StudentT(deg_free=5, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [10.0],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                },
                            "laplace": True
                            },
                        "Student_t_approx_gauss": {
                            "model": GPy.likelihoods.StudentT(deg_free=1000, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [self.var],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                },
                            "laplace": True
                            },
                        "Student_t_log": {
                            "model": GPy.likelihoods.StudentT(gp_link=link_functions.Log(), deg_free=5, sigma2=self.var),
                            "grad_params": {
                                "names": ["t_noise"],
                                "vals": [self.var],
                                "constraints": [("t_noise", constrain_positive), ("deg_free", constrain_fixed)]
                                },
                            "laplace": True
                            },
                        "Gaussian_default": {
                            "model": GPy.likelihoods.Gaussian(variance=self.var),
                            "grad_params": {
                                "names": ["variance"],
                                "vals": [self.var],
                                "constraints": [("variance", constrain_positive)]
                                },
                            "laplace": True,
                            "ep": True
                            },
                        #"Gaussian_log": {
                            #"model": GPy.likelihoods.gaussian(gp_link=link_functions.Log(), variance=self.var, D=self.D, N=self.N),
                            #"grad_params": {
                                #"names": ["noise_model_variance"],
                                #"vals": [self.var],
                                #"constraints": [constrain_positive]
                                #},
                            #"laplace": True
                            #},
                        #"Gaussian_probit": {
                            #"model": GPy.likelihoods.gaussian(gp_link=link_functions.Probit(), variance=self.var, D=self.D, N=self.N),
                            #"grad_params": {
                                #"names": ["noise_model_variance"],
                                #"vals": [self.var],
                                #"constraints": [constrain_positive]
                                #},
                            #"laplace": True
                            #},
                        #"Gaussian_log_ex": {
                            #"model": GPy.likelihoods.gaussian(gp_link=link_functions.Log_ex_1(), variance=self.var, D=self.D, N=self.N),
                            #"grad_params": {
                                #"names": ["noise_model_variance"],
                                #"vals": [self.var],
                                #"constraints": [constrain_positive]
                                #},
                            #"laplace": True
                            #},
                        "Bernoulli_default": {
                            "model": GPy.likelihoods.Bernoulli(),
                            "link_f_constraints": [partial(constrain_bounded, lower=0, upper=1)],
                            "laplace": True,
                            "Y": self.binary_Y,
                            "ep": True
                            },
                        #"Exponential_default": {
                            #"model": GPy.likelihoods.exponential(),
                            #"link_f_constraints": [constrain_positive],
                            #"Y": self.positive_Y,
                            #"laplace": True,
                        #},
                        #"Poisson_default": {
                            #"model": GPy.likelihoods.poisson(),
                            #"link_f_constraints": [constrain_positive],
                            #"Y": self.integer_Y,
                            #"laplace": True,
                            #"ep": False #Should work though...
                        #},
                        #"Gamma_default": {
                            #"model": GPy.likelihoods.gamma(),
                            #"link_f_constraints": [constrain_positive],
                            #"Y": self.positive_Y,
                            #"laplace": True
                        #}
                    }

        for name, attributes in noise_models.iteritems():
            model = attributes["model"]
            if "grad_params" in attributes:
                params = attributes["grad_params"]
                param_vals = params["vals"]
                param_names= params["names"]
                param_constraints = params["constraints"]
            else:
                params = []
                param_vals = []
                param_names = []
                constrain_positive = []
                param_constraints = [] # ??? TODO: Saul to Fix.
            if "link_f_constraints" in attributes:
                link_f_constraints = attributes["link_f_constraints"]
            else:
                link_f_constraints = []
            if "Y" in attributes:
                Y = attributes["Y"].copy()
            else:
                Y = self.Y.copy()
            if "f" in attributes:
                f = attributes["f"].copy()
            else:
                f = self.f.copy()
            if "laplace" in attributes:
                laplace = attributes["laplace"]
            else:
                laplace = False
            if "ep" in attributes:
                ep = attributes["ep"]
            else:
                ep = False

            #if len(param_vals) > 1:
                #raise NotImplementedError("Cannot support multiple params in likelihood yet!")

            #Required by all
            #Normal derivatives
            yield self.t_logpdf, model, Y, f
            yield self.t_dlogpdf_df, model, Y, f
            yield self.t_d2logpdf_df2, model, Y, f
            #Link derivatives
            yield self.t_dlogpdf_dlink, model, Y, f, link_f_constraints
            yield self.t_d2logpdf_dlink2, model, Y, f, link_f_constraints
            if laplace:
                #Laplace only derivatives
                yield self.t_d3logpdf_df3, model, Y, f
                yield self.t_d3logpdf_dlink3, model, Y, f, link_f_constraints
                #Params
                yield self.t_dlogpdf_dparams, model, Y, f, param_vals, param_names, param_constraints
                yield self.t_dlogpdf_df_dparams, model, Y, f, param_vals, param_names, param_constraints
                yield self.t_d2logpdf2_df2_dparams, model, Y, f, param_vals, param_names, param_constraints
                #Link params
                yield self.t_dlogpdf_link_dparams, model, Y, f, param_vals, param_names, param_constraints
                yield self.t_dlogpdf_dlink_dparams, model, Y, f, param_vals, param_names, param_constraints
                yield self.t_d2logpdf2_dlink2_dparams, model, Y, f, param_vals, param_names, param_constraints

                #laplace likelihood gradcheck
                yield self.t_laplace_fit_rbf_white, model, self.X, Y, f, self.step, param_vals, param_names, param_constraints
            if ep:
                #ep likelihood gradcheck
                yield self.t_ep_fit_rbf_white, model, self.X, Y, f, self.step, param_vals, param_names, param_constraints


        self.tearDown()

    #############
    # dpdf_df's #
    #############
    @with_setup(setUp, tearDown)
    def t_logpdf(self, model, Y, f):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        print model._get_params()
        np.testing.assert_almost_equal(
                               model.pdf(f.copy(), Y.copy()),
                               np.exp(model.logpdf(f.copy(), Y.copy()))
                               )

    @with_setup(setUp, tearDown)
    def t_dlogpdf_df(self, model, Y, f):
        print "\n{}".format(inspect.stack()[0][3])
        self.description = "\n{}".format(inspect.stack()[0][3])
        logpdf = functools.partial(model.logpdf, y=Y)
        dlogpdf_df = functools.partial(model.dlogpdf_df, y=Y)
        grad = GradientChecker(logpdf, dlogpdf_df, f.copy(), 'g')
        grad.randomize()
        grad.checkgrad(verbose=1)
        print model
        assert grad.checkgrad()

    @with_setup(setUp, tearDown)
    def t_d2logpdf_df2(self, model, Y, f):
        print "\n{}".format(inspect.stack()[0][3])
        dlogpdf_df = functools.partial(model.dlogpdf_df, y=Y)
        d2logpdf_df2 = functools.partial(model.d2logpdf_df2, y=Y)
        grad = GradientChecker(dlogpdf_df, d2logpdf_df2, f.copy(), 'g')
        grad.randomize()
        grad.checkgrad(verbose=1)
        print model
        assert grad.checkgrad()

    @with_setup(setUp, tearDown)
    def t_d3logpdf_df3(self, model, Y, f):
        print "\n{}".format(inspect.stack()[0][3])
        d2logpdf_df2 = functools.partial(model.d2logpdf_df2, y=Y)
        d3logpdf_df3 = functools.partial(model.d3logpdf_df3, y=Y)
        grad = GradientChecker(d2logpdf_df2, d3logpdf_df3, f.copy(), 'g')
        grad.randomize()
        grad.checkgrad(verbose=1)
        print model
        assert grad.checkgrad()

    ##############
    # df_dparams #
    ##############
    @with_setup(setUp, tearDown)
    def t_dlogpdf_dparams(self, model, Y, f, params, params_names, param_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        assert (
                dparam_checkgrad(model.logpdf, model.dlogpdf_dtheta,
                    params, params_names, args=(f, Y), constraints=param_constraints,
                    randomize=False, verbose=True)
                )

    @with_setup(setUp, tearDown)
    def t_dlogpdf_df_dparams(self, model, Y, f, params, params_names, param_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        assert (
                dparam_checkgrad(model.dlogpdf_df, model.dlogpdf_df_dtheta,
                    params, params_names, args=(f, Y), constraints=param_constraints,
                    randomize=False, verbose=True)
                )

    @with_setup(setUp, tearDown)
    def t_d2logpdf2_df2_dparams(self, model, Y, f, params, params_names, param_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        assert (
                dparam_checkgrad(model.d2logpdf_df2, model.d2logpdf_df2_dtheta,
                    params, params_names, args=(f, Y), constraints=param_constraints,
                    randomize=False, verbose=True)
                )

    ################
    # dpdf_dlink's #
    ################
    @with_setup(setUp, tearDown)
    def t_dlogpdf_dlink(self, model, Y, f, link_f_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        logpdf = functools.partial(model.logpdf_link, y=Y)
        dlogpdf_dlink = functools.partial(model.dlogpdf_dlink, y=Y)
        grad = GradientChecker(logpdf, dlogpdf_dlink, f.copy(), 'g')

        #Apply constraints to link_f values
        for constraint in link_f_constraints:
            constraint('g', grad)

        grad.randomize()
        print grad
        grad.checkgrad(verbose=1)
        assert grad.checkgrad()

    @with_setup(setUp, tearDown)
    def t_d2logpdf_dlink2(self, model, Y, f, link_f_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        dlogpdf_dlink = functools.partial(model.dlogpdf_dlink, y=Y)
        d2logpdf_dlink2 = functools.partial(model.d2logpdf_dlink2, y=Y)
        grad = GradientChecker(dlogpdf_dlink, d2logpdf_dlink2, f.copy(), 'g')

        #Apply constraints to link_f values
        for constraint in link_f_constraints:
            constraint('g', grad)

        grad.randomize()
        grad.checkgrad(verbose=1)
        print grad
        assert grad.checkgrad()

    @with_setup(setUp, tearDown)
    def t_d3logpdf_dlink3(self, model, Y, f, link_f_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        d2logpdf_dlink2 = functools.partial(model.d2logpdf_dlink2, y=Y)
        d3logpdf_dlink3 = functools.partial(model.d3logpdf_dlink3, y=Y)
        grad = GradientChecker(d2logpdf_dlink2, d3logpdf_dlink3, f.copy(), 'g')

        #Apply constraints to link_f values
        for constraint in link_f_constraints:
            constraint('g', grad)

        grad.randomize()
        grad.checkgrad(verbose=1)
        print grad
        assert grad.checkgrad()

    #################
    # dlink_dparams #
    #################
    @with_setup(setUp, tearDown)
    def t_dlogpdf_link_dparams(self, model, Y, f, params, param_names, param_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        assert (
                dparam_checkgrad(model.logpdf_link, model.dlogpdf_link_dtheta,
                    params, param_names, args=(f, Y), constraints=param_constraints,
                    randomize=False, verbose=True)
                )

    @with_setup(setUp, tearDown)
    def t_dlogpdf_dlink_dparams(self, model, Y, f, params, param_names, param_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        assert (
                dparam_checkgrad(model.dlogpdf_dlink, model.dlogpdf_dlink_dtheta,
                    params, param_names, args=(f, Y), constraints=param_constraints,
                    randomize=False, verbose=True)
                )

    @with_setup(setUp, tearDown)
    def t_d2logpdf2_dlink2_dparams(self, model, Y, f, params, param_names, param_constraints):
        print "\n{}".format(inspect.stack()[0][3])
        print model
        assert (
                dparam_checkgrad(model.d2logpdf_dlink2, model.d2logpdf_dlink2_dtheta,
                    params, param_names, args=(f, Y), constraints=param_constraints,
                    randomize=False, verbose=True)
                )

    ################
    # laplace test #
    ################
    @with_setup(setUp, tearDown)
    def t_laplace_fit_rbf_white(self, model, X, Y, f, step, param_vals, param_names, constraints):
        print "\n{}".format(inspect.stack()[0][3])
        #Normalize
        Y = Y/Y.max()
        white_var = 1e-6
        kernel = GPy.kern.rbf(X.shape[1]) + GPy.kern.white(X.shape[1])
        laplace_likelihood = GPy.inference.latent_function_inference.LaplaceInference()
        m = GPy.core.GP(X.copy(), Y.copy(), kernel, likelihood=model, inference_method=laplace_likelihood)
        m.ensure_default_constraints()
        m['white'].constrain_fixed(white_var)

        #Set constraints
        for constrain_param, constraint in constraints:
            constraint(constrain_param, m)

        print m
        m.randomize()

        #Set params
        for param_num in range(len(param_names)):
            name = param_names[param_num]
            m[name] = param_vals[param_num]

        #m.optimize(max_iters=8)
        print m
        m.checkgrad(verbose=1, step=step)
        #if not m.checkgrad(step=step):
            #m.checkgrad(verbose=1, step=step)
            #import ipdb; ipdb.set_trace()
            #NOTE this test appears to be stochastic for some likelihoods (student t?)
            # appears to all be working in test mode right now...
        assert m.checkgrad(step=step)

    ###########
    # EP test #
    ###########
    @with_setup(setUp, tearDown)
    def t_ep_fit_rbf_white(self, model, X, Y, f, step, param_vals, param_names, constraints):
        print "\n{}".format(inspect.stack()[0][3])
        #Normalize
        Y = Y/Y.max()
        white_var = 1e-6
        kernel = GPy.kern.rbf(X.shape[1]) + GPy.kern.white(X.shape[1])
        ep_inf = GPy.inference.latent_function_inference.EP()
        m = GPy.core.GP(X.copy(), Y.copy(), kernel=kernel, likelihood=model, inference_method=ep_inf)
        m.ensure_default_constraints()
        m['white'].constrain_fixed(white_var)

        for param_num in range(len(param_names)):
            name = param_names[param_num]
            m[name] = param_vals[param_num]
            constraints[param_num](name, m)

        m.randomize()
        m.checkgrad(verbose=1, step=step)
        print m
        assert m.checkgrad(step=step)


class LaplaceTests(unittest.TestCase):
    """
    Specific likelihood tests, not general enough for the above tests
    """

    def setUp(self):
        self.N = 5
        self.D = 3
        self.X = np.random.rand(self.N, self.D)*10

        self.real_std = 0.1
        noise = np.random.randn(*self.X[:, 0].shape)*self.real_std
        self.Y = (np.sin(self.X[:, 0]*2*np.pi) + noise)[:, None]
        self.f = np.random.rand(self.N, 1)

        self.var = 0.2

        self.var = np.random.rand(1)
        self.stu_t = GPy.likelihoods.StudentT(deg_free=5, sigma2=self.var)
        self.gauss = GPy.likelihoods.Gaussian(gp_link=link_functions.Log(), variance=self.var)

        #Make a bigger step as lower bound can be quite curved
        self.step = 1e-6

    def tearDown(self):
        self.stu_t = None
        self.gauss = None
        self.Y = None
        self.f = None
        self.X = None

    def test_gaussian_d2logpdf_df2_2(self):
        print "\n{}".format(inspect.stack()[0][3])
        self.Y = None
        self.gauss = None

        self.N = 2
        self.D = 1
        self.X = np.linspace(0, self.D, self.N)[:, None]
        self.real_std = 0.2
        noise = np.random.randn(*self.X.shape)*self.real_std
        self.Y = np.sin(self.X*2*np.pi) + noise
        self.f = np.random.rand(self.N, 1)
        self.gauss = GPy.likelihoods.Gaussian(variance=self.var)

        dlogpdf_df = functools.partial(self.gauss.dlogpdf_df, y=self.Y)
        d2logpdf_df2 = functools.partial(self.gauss.d2logpdf_df2, y=self.Y)
        grad = GradientChecker(dlogpdf_df, d2logpdf_df2, self.f.copy(), 'g')
        grad.randomize()
        grad.checkgrad(verbose=1)
        self.assertTrue(grad.checkgrad())

    def test_laplace_log_likelihood(self):
        debug = False
        real_std = 0.1
        initial_var_guess = 0.5

        #Start a function, any function
        X = np.linspace(0.0, np.pi*2, 100)[:, None]
        Y = np.sin(X) + np.random.randn(*X.shape)*real_std
        Y = Y/Y.max()
        #Yc = Y.copy()
        #Yc[75:80] += 1
        kernel1 = GPy.kern.rbf(X.shape[1]) + GPy.kern.white(X.shape[1])
        #FIXME: Make sure you can copy kernels when params is fixed
        #kernel2 = kernel1.copy()
        kernel2 = GPy.kern.rbf(X.shape[1]) + GPy.kern.white(X.shape[1])

        gauss_distr1 = GPy.likelihoods.Gaussian(variance=initial_var_guess)
        exact_inf = GPy.inference.latent_function_inference.ExactGaussianInference()
        m1 = GPy.core.GP(X, Y.copy(), kernel=kernel1, likelihood=gauss_distr1, inference_method=exact_inf)
        m1['white'].constrain_fixed(1e-6)
        m1['variance'] = initial_var_guess
        m1['variance'].constrain_bounded(1e-4, 10)
        m1['rbf'].constrain_bounded(1e-4, 10)
        m1.ensure_default_constraints()
        m1.randomize()

        gauss_distr2 = GPy.likelihoods.Gaussian(variance=initial_var_guess)
        laplace_inf = GPy.inference.latent_function_inference.LaplaceInference()
        m2 = GPy.core.GP(X, Y.copy(), kernel=kernel2, likelihood=gauss_distr2, inference_method=laplace_inf)
        m2.ensure_default_constraints()
        m2['white'].constrain_fixed(1e-6)
        m2['rbf'].constrain_bounded(1e-4, 10)
        m2['variance'].constrain_bounded(1e-4, 10)
        m2.randomize()

        if debug:
            print m1
            print m2
        optimizer = 'scg'
        print "Gaussian"
        m1.optimize(optimizer, messages=debug)
        print "Laplace Gaussian"
        m2.optimize(optimizer, messages=debug)
        if debug:
            print m1
            print m2

        m2._set_params(m1._get_params())

        #Predict for training points to get posterior mean and variance
        post_mean, post_var, _, _ = m1.predict(X)
        post_mean_approx, post_var_approx, _, _ = m2.predict(X)

        if debug:
            import pylab as pb
            pb.figure(5)
            pb.title('posterior means')
            pb.scatter(X, post_mean, c='g')
            pb.scatter(X, post_mean_approx, c='r', marker='x')

            pb.figure(6)
            pb.title('plot_f')
            m1.plot_f(fignum=6)
            m2.plot_f(fignum=6)
            fig, axes = pb.subplots(2, 1)
            fig.suptitle('Covariance matricies')
            a1 = pb.subplot(121)
            a1.matshow(m1.likelihood.covariance_matrix)
            a2 = pb.subplot(122)
            a2.matshow(m2.likelihood.covariance_matrix)

            pb.figure(8)
            pb.scatter(X, m1.likelihood.Y, c='g')
            pb.scatter(X, m2.likelihood.Y, c='r', marker='x')



        #Check Y's are the same
        np.testing.assert_almost_equal(m1.Y, m2.Y, decimal=5)
        #Check marginals are the same
        np.testing.assert_almost_equal(m1.log_likelihood(), m2.log_likelihood(), decimal=2)
        #Check marginals are the same with random
        m1.randomize()
        m2._set_params(m1._get_params())
        np.testing.assert_almost_equal(m1.log_likelihood(), m2.log_likelihood(), decimal=2)

        #Check they are checkgradding
        #m1.checkgrad(verbose=1)
        #m2.checkgrad(verbose=1)
        self.assertTrue(m1.checkgrad())
        self.assertTrue(m2.checkgrad())

if __name__ == "__main__":
    print "Running unit tests"
    unittest.main()