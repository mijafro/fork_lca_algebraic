import warnings

import ipywidgets as widgets
import seaborn as sns
from SALib.analyze import sobol
from SALib.sample import saltelli
from ipywidgets import interact
from matplotlib import pyplot as plt

from .base_utils import _method_unit, _eprint
from .lca import *
from .lca import _expanded_names_to_names
from .params import _variable_params, _fixed_params, _param_registry


def _heatmap(df, title, vmax, ints=False):
    ''' Produce heatmap of a dataframe'''
    fig, ax = plt.subplots(figsize=(17, 17))
    sns.heatmap(df.transpose(), cmap="gist_heat_r", vmax=vmax, annot=True, fmt='.0f' if ints else 'f', square=True)
    plt.title(title, fontsize=20)
    ax.tick_params(axis="x", labelsize=18)
    ax.tick_params(axis="y", labelsize=18)


def oat_matrix(model, impacts, n=10):
    '''Generates a heatmap of the incertitude of the model, varying input parameters one a a time.'''

    # Compile model into lambda functions for fast LCA
    lambdas, required_params = preMultiLCAAlgebric(model, impacts)

    required_param_names = _expanded_names_to_names(required_params)
    required_params = {key: _param_registry()[key] for key in required_param_names}
    var_params = _variable_params(required_param_names)


    change = np.zeros((len(var_params), len(impacts)))

    for iparam, param in enumerate(var_params.values()):
        params = {param.name: param.default for param in required_params.values()}

        # Compute range of values for given param
        params[param.name] = param.range(n)

        # Compute LCA
        df = postMultiLCAAlgebric(impacts, lambdas, **params)

        # Compute change
        change[iparam] = (df.max() - df.min()) / df.median() * 100

    # Build final heatmap
    change = pd.DataFrame(change, index=var_params.keys(), columns=[imp[2] for imp in impacts])
    _heatmap(change.transpose(), 'Change of impacts per variability of the input parameters (%)', 100, ints=True)


def _display_tabs(titlesAndContentF):
    '''Generate tabs'''
    tabs = []
    titles = []
    for title, content_f in titlesAndContentF:
        titles.append(title)

        tab = widgets.Output()
        with tab:
            content_f()
        tabs.append(tab)

    res = widgets.Tab(children=tabs)
    for i, title in enumerate(titles):
        res.set_title(i, title)
    display(res)


def oat_dasboard(modelOrLambdas, impacts, varying_param: ParamDef, n=10, all_param_names=None):
    '''
    Analyse the evolution of impacts for a single parameter. The other parameters are set to their default values.

    Parameters
    ----------
    model : activity, or lambdas as precomputed by preMultiLCAAlgebric, for faster computation
    impacts : set of methods
    param: parameter to analyse
    n: number of samples of the parameter
    '''

    if all_param_names == None:
        all_param_names = _param_registry().keys()

    params = {name: _param_registry()[name].default for name in all_param_names}

    # Compute range of values for given param
    params[varying_param.name] = varying_param.range(n)

    # print("Params: ", params)

    if isinstance(modelOrLambdas, Activity):
        df = multiLCAAlgebric(modelOrLambdas, impacts, **params)
    else:
        df = postMultiLCAAlgebric(impacts, modelOrLambdas, **params)

    # Add X values in the table
    pname = varying_param.name
    if varying_param.unit:
        pname = '%s [%s]' % (pname, varying_param.unit)
    df.insert(0, pname, varying_param.range(n))
    df = df.set_index(pname)

    def table():
        display(df)

    def graph():

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            nb_rows = len(impacts) // 3 + 1

            fig, axes = plt.subplots(figsize=(15, 15))

            axes = df.plot(
                ax=axes, sharex=True, subplots=True,
                layout=(nb_rows, 3),
                # legend=None,
                kind='line' if varying_param.type == ParamType.FLOAT else 'bar')

            axes = axes.flatten()

            for ax, impact in zip(axes, impacts):
                ax.set_ylim(ymin=0)
                ax.set_ylabel(_method_unit(impact))

            plt.show(fig)

    def change():

        ch = (df.max() - df.min()) / df.median() * 100
        fig, ax = plt.subplots(figsize=(9, 6))
        plt.title('Relative change for %s' % df.index.name)
        ch.plot(kind='barh', rot=30)
        ax.set_xlabel('Relative change of the median value (%)')
        plt.tight_layout()
        plt.show(fig)

    _display_tabs([
        ("Graphs", graph),
        ("Data", table),
        ("Variation", change)
    ])


def oat_dashboard_interact(model, methods):
    '''Interative dashboard, with a dropdown for selecting parameter'''

    lambdas, required_params = preMultiLCAAlgebric(model, methods)

    required_params = _expanded_names_to_names(required_params)

    def process_func(param):
        oat_dasboard(lambdas, methods, _param_registry()[param], all_param_names=required_params)

    paramlist = list(_variable_params(required_params).keys())
    interact(process_func, param=paramlist)


def _stochastics(modelOrLambdas, methods, n=1000):
    ''' Compute stochastic impacts for later analysis of incertitude '''

    # Extract variable names
    param_names = list(_variable_params().keys())
    problem = {
        'num_vars': len(param_names),
        'names': param_names,
        'bounds': [[0, 1]] * len(param_names)
    }

    print("Generating samples ...")
    X = saltelli.sample(problem, n, calc_second_order=True)

    # Map normalized 0-1 random values into real values
    print("Transforming samples ...")
    params = dict()
    for i, param_name in enumerate(param_names):
        param = _param_registry()[param_name]
        vals = list(map(lambda v: param.rand(v), X[:, i]))
        params[param_name] = vals

    # Add static parameters
    for param in _fixed_params().values():
        params[param.name] = param.default

    print("Processing LCA ...")
    if isinstance(modelOrLambdas, Activity):
        Y = multiLCAAlgebric(modelOrLambdas, methods, **params)
    else:
        Y = postMultiLCAAlgebric(methods, modelOrLambdas, **params)

    return problem, X, Y


def _sobols(methods, problem, Y):
    ''' Computes sobols indices'''
    s1 = np.zeros((len(problem['names']), len(methods)))
    st = np.zeros((len(problem['names']), len(methods)))

    for i, method in enumerate(methods):

        try:
            y = Y[Y.columns[i]]
            res = sobol.analyze(problem, y.to_numpy(), calc_second_order=True)
            st[:, i] = res["ST"]
            s1[:, i] = res["S1"]

        except Exception as e:
            _eprint("Sobol failed on %s" % method[2], e)
    return (s1, st)


def _incer_stochastic_matrix(methods, param_names, Y, st):
    ''' Internal method computing matrix of parameter importance '''

    def draw(mode):

        if mode == 'sobol':
            data = st
        else:
            # If percent, express result as percentage of standard deviation / mean
            data = np.zeros((len(param_names), len(methods)))
            for i, method in enumerate(methods):
                # Total variance
                var = np.var(Y[Y.columns[i]])
                mean = np.mean(Y[Y.columns[i]])
                if mean != 0:
                    data[:, i] = np.sqrt((st[:, i] * var)) / mean * 100

        df = pd.DataFrame(data, index=param_names, columns=[method_name(method) for method in methods])
        _heatmap(
            df.transpose(),
            title="Relative deviation of impacts (%)" if mode == 'percent' else "Sobol indices (part of variability)",
            vmax=100 if mode == 'percent' else 1,
            ints=mode == 'percent')

    interact(draw, mode=[('Raw sobol indices (ST)', 'sobol'), ('Deviation (ST) / mean', 'percent')])


def incer_stochastic_matrix(modelOrLambdas, methods, n=1000):
    ''' Method computing matrix of parameter importance '''

    problem, X, Y = _stochastics(modelOrLambdas, methods, n)

    print("Processing Sobol indices ...")
    s1, st = _sobols(methods, problem, Y)

    _incer_stochastic_matrix(methods, problem['names'], Y, st)


def _incer_stochastic_violin(methods, Y):
    ''' Internal method for computing violin graph of impacts '''

    nb_rows = math.ceil(len(methods) / 3)
    fig, axes = plt.subplots(nb_rows, 3, figsize=(15, 15), sharex=True)

    for imethod, method, ax in zip(range(len(methods)), methods, axes.flatten()):
        ax.violinplot(Y[Y.columns[imethod]], showmedians=True)
        ax.title.set_text(method_name(method))
        ax.set_ylim(ymin=0)
        ax.set_ylabel(_method_unit(method))

    plt.tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=False)
    plt.show(fig)


def incer_stochastic_violin(modelOrLambdas, methods, n=1000):
    ''' Method for computing violin graph of impacts '''

    problem, X, Y = _stochastics(modelOrLambdas, methods, n)

    _incer_stochastic_violin(methods, Y)


def _incer_stochastic_variations(methods, Y, param_names, sobols1):
    ''' Method for computing violin graph of impacts '''
    method_names = [method_name(method) for method in methods]

    std = np.std(Y)
    mean = np.mean(Y)

    fig = plt.figure(num=None, figsize=(12, 6), dpi=80, facecolor='w', edgecolor='k')
    ax = plt.gca()
    tab20b = plt.get_cmap('tab20b')
    tab20c = plt.get_cmap('tab20c')
    ax.set_prop_cycle('color', [tab20b(k) if k < 1 else tab20c(k - 1) for k in np.linspace(0, 2, 40)])

    relative_variance_pct = std * std / (mean * mean) * 100
    totplt = plt.bar(np.arange(len(method_names)), relative_variance_pct, 0.8)

    sum = np.zeros(len(methods))

    plots = [totplt[0]]

    data = np.zeros((len(param_names) + 2, len(methods)))
    data[0, :] = mean
    data[1, :] = std

    for i_param, param_name in enumerate(param_names):
        s1 = sobols1[i_param, :]
        data[i_param + 2, :] = s1

        curr_bar = s1 * relative_variance_pct
        curr_plt = plt.bar(np.arange(len(method_names)), curr_bar, 0.8, bottom=sum)
        sum += curr_bar
        plots.append(curr_plt[0])

    plt.legend(plots, ['Higher order'] + param_names)
    plt.xticks(np.arange(len(method_names)), method_names, rotation=90)
    plt.title("variance / mean² (%)")
    plt.show(fig)

    # Show raw data
    rows = ["mean", "std"] + ["s1(%s)" % param for param in param_names]
    df = pd.DataFrame(data, index=rows, columns=[method_name(method) for method in methods])
    display(df)


def incer_stochastic_dasboard(model, methods, n=1000):
    ''' Generates a dashboard with several statistics : matrix of parameter incertitude, violin diagrams, ...'''

    problem, X, Y = _stochastics(model, methods, n)
    param_names = problem['names']

    print("Processing Sobol indices ...")
    s1, st = _sobols(methods, problem, Y)

    def violin():
        _incer_stochastic_violin(methods, Y)

    def variation():
        _incer_stochastic_variations(methods, Y, param_names, s1)

    def matrix():
        _incer_stochastic_matrix(methods, problem['names'], Y, st)

    _display_tabs([
        ("Violin graphs", violin),
        ("Impact variations", variation),
        ("Sobol matrix", matrix)
    ])