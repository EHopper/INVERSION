""" Extract partial derivatives matrix for an inversion.

These codes are used to convert from the Frechet kernels calculated by MINEOS
into kernels that are useful for our inversion model.


************  MINEOS G MATRIX *************
We start by assembling the MINEOS Frechet kernels into a more useful G matrix,
    n_Love_periods+n_Rayleigh_periods x n_depth_points*5 (SV, SH, PV, PH, ETA)
This is filled in by the frechet kernels for each period - first the vsv and
vsh T frechet kernels (sensitivities from Love) rows, then the vsv, (vsh set
to 0), vpv, vph, eta S frechet kernels (sensitivities from Rayleigh) rows:


********** INVERSION G MATRIX ************
The Frechet kernels from MINEOS are given at the same depths as those in
the MINEOS model card, as a function of the model card v(z).  However, we
want to invert for a model in a different format, p, so we need to adjust
the kernels accordingly.

Let   m:    old model, as a function of depth, from MINEOS card
            multiple parameters - [vsv, vsh, vpv, vph, eta]
      p:    new model
            multiple parameters - [s, t]
      c:    observed phase velocities, Love stacked on top of Rayleigh

The MINEOS kernels are a matrix of dc/dm
    i.e.   dc_0/dvsv_0, ..., dc_0/dvsv_M, dc_0/dvsh_0, ..., dc_0/deta_M
        [       :     ,  : ,      :     ,      :     ,  : ,      :      ]
            dc_N/dvsv_0, ..., dc_N/dvsv_M, dc_N/dvsh_0, ..., dcN_deta_M

We want a matrix of dc/dp
    i.e.   dc_0/ds_0, ..., dc_0/ds_P, dc_0/dt_0, ..., dc_0/dt_D
        [       :   ,  : ,    :     ,    :     ,  : ,    :      ]
           dc_N/ds_0, ..., dc_N/ds_P, dc_N/dt_0, ..., dc_N/dt_D


As dx/dy = dx/da * da/dy, we need to find the matrix dm/dp
    i.e.   dvsv_0/ds_0, ..., dvsv_0/ds_P, dvsv_0/dt_0, ..., dvsv_0/dt_D
                :     ,  : ,    :       ,    :       ,  : ,    :
        [  dvsv_M/ds_0, ..., dvsv_M/ds_P, dvsv_M/dt_0, ..., dvsv_M/dt_D  ]
           dvsh_0/ds_0, ..., dvsh_0/ds_P, dvsh_0/dt_0, ..., dvsh_0/dt_D
                :     ,  : ,    :       ,    :       ,  : ,    :
           deta_M/ds_0, ..., deta_M/ds_P, deta_M/dt_0, ..., deta_M/dt_D



***************** THE dm/dp MATRIX *******************
To convert the MINEOS kernels (dc/dm) to inversion model kernels (dc/dp),
we need to define the matrix dm/dp (dc/dp = dc/dm * dm/dp).  We divide
our inversion model, p, into two parts: the defined velocities at various
depths (s) and the depth and thickness of certain boundary layers of
interest (t).

It is simple to write an expression for m = v(z) in terms of the parameters
in p = [s; t].  To find dm/dp, all we need to do if take the partial derivative
of these expressions with respect to p.  The tricky parts of this...
    a. The dependence of m on p is different for s and for t
    b. The dependence of m on s is different for v(z) defined far from the
       varied point in p, p_i (i.e. separated from p_i by another node), and
       is different for those points immediately above and immediately below
       the node p_i (i.e. at depths between the depths of p_i-1 and p_i+1).
    c. The same is true for t, except it is even more complicated because we
       have set up t as varying the depth to a boundary layer with fixed width.
       As such, the points in z within the variable depth layer, the points in
       z within the boundary layer of fixed with but variable edge depths, and
       the points in z beneath the boundary layer with a fixed depth of base
       are all differently dependent on the variation in t.

       Note that for simplicity, we are not trying to account for the fact that
       sometimes a change in t will cause a point in z to switch from below to
       above a node (or vice versa).  This may cause issues down the line...
That said, the equations for m = f(p) are pretty simple in and of themselves,
so the actual partial derivatives are easy to work out - but how they are
assigned in the matrix dm/dp needs a bit more attention.

******************  THE dc/dp MATRIX ******************
Once we have G_MINEOS (i.e. dc/dm) and dm/dp, we can get our output Inversion
G matrix by a simple matrix multiplication.

"""

import typing
import numpy as np
import numpy.matlib as npmatlib
import pandas as pd

from util import define_models


def _build_partial_derivatives_matrix(kernels:pd.DataFrame,
                                      model:define_models.InversionModel,
                                      setup_model:define_models.SetupModel):
    """ Make partial derivative matrix, G, from the Frechet kernels.

    First, assemble the G_MINEOS matrix from kernels in the format
            [horizontal stack of Vsv, Vsh, Vpv, Vph, Eta kernels]
            [vertically stacked by period]

    Now, need to convert this to something useful for the inversion
    via _convert_to_model_kernels() and _scale_dvsv_dp_to_other_variables().

    The final G matrix is from the matrix multiplication: G_MINEOS * dm_dp_mat,
    i.e. dc/dp = dc/dm * dm/dp.


    Arguments:
        kernels:
            - pandas DataFrame
            - Units:    assumes velocities in km/s
            - Rayleigh wave kernels calculated in MINEOS
        model:
            - define_models.InversionModel
            - Units:    seismological (km/s, km)
            - Current iteration of velocity (Vsv) model
        setup_model:
            - define_models.SetupModel
            - Units:    seismological (km/s, km)
            - Initial model constraints, including fixed parameters describing
              the relationship between Vsv and other model parameters used
              by MINEOS.

    Returns:
        G_inversion_model:
            - (n_periods, n_inversion_model_depths + n_boundary_layers) np.array
            - Units:    assumes velocities in km/s
            - Partial derivatives matrix for use in inversion.

    """
    G_MINEOS = _build_MINEOS_G_matrix(kernels)

    # Convert to kernels for the model parameters we are inverting for
    dvsv_dp_mat = _convert_to_model_kernels(kernels['z'].unique(), model)
    # Frechet kernels cover Vsv, Vsh, Vpv, Vph, Eta.  We assume that eta is
    # kept constant, and all of the others are linearly dependent on Vsv.
    dm_dp_mat = _scale_dvsv_dp_to_other_variables(dvsv_dp_mat, setup_model)
    G_inversion_model = np.matmul(G_MINEOS, dm_dp_mat)

    return G_inversion_model

def _build_MINEOS_G_matrix(kernels:pd.DataFrame):
    """ Assemble the G matrix from MINEOS.

    We start by assembling the MINEOS Frechet kernels into a useful G matrix,
        n_Love_periods+n_Rayleigh_periods x n_depth_points*5
                                            (SV, SH, PV, PH, ETA)
    This is filled in by the frechet kernels for each period - first the vsv and
    vsh T frechet kernels (sensitivities from Love) rows, then the vsv, (vsh set
    to 0), vpv, vph, eta S frechet kernels (sensitivities from Rayleigh) rows:

    G_MINEOS matrix:
              T_Vsv_p1  T_Vsh_p1      0         0         0
              T_Vsv_p2  T_Vsh_p2      0         0         0
        [     S_Vsv_p1     0      S_Vpv_p1  S_Vph_p1  S_eta_p1    ]
              S_Vsv_p2     0      S_Vpv_p2  S_Vph_p2  S_eta_p2
              S_Vsv_p2     0      S_Vpv_p2  S_Vph_p2  S_eta_p2

    where, e.g. T_Vsv_p1 is the Frechet kernel for Toroidal Vsv sensitivity
    for the first (Love) period. Frechet kernels are depth dependent, so each
    entry in the matrix above (including the 0) is actually a row vector
    n_depth_points long.

    For now, we are only using Rayleigh waves, so in the above explanation,
    n_Love_periods = 0, i.e. there are no rows in G for the T_*** kernels.
    """

    periods = np.unique(kernels['period'])

    G_Rayleigh = _hstack_frechet_kernels(kernels, periods[0])
    # G_Love = _hstack_frechet_kernels(love, periods[0])
    for i_p in range(1,len(periods)):
        G_Rayleigh = np.vstack((G_Rayleigh,
                               _hstack_frechet_kernels(kernels, periods[i_p])))
        # G_Love = np.vstack((G_Love,
        #                     _hstack_frechet_kernels(love, periods[i_p])))

    # G_MINEOS is dc/dm matrix
    G_MINEOS = G_Rayleigh #np.vstack((G_Love, G_Rayleigh))

    return G_MINEOS

def _hstack_frechet_kernels(kernels, period:float):
    """ Append all of the relevent Frechet kernels into a row of the G matrix.

    Different parameters are of interest for Rayleigh (Vsv, Vpv, Vph, Eta)
    and Love (Vsv, Vsh) waves.

    Arguments:
        kernels:
            - pd.DataFrame
            - Frechet kernels across all periods
        period:
            - float
            - Units:    seconds
            - Period of interest.
            - Should match a period in kernel.period.

    Returns:
        Row vector:
            - (n_model_points, ) np.array
            - Units:     assumes velocities in km/s
            - Vector contains the Vsv, Vsh, Vpv, Vph, Eta kernels for the
              requested period.
            - Note that some of these are filled with zeros, depending on if
              the kernel is a Love or Rayleigh kernel.
    """

    # Note: To have kernels scaled for changes in velocity in SI
    #       units (i.e. m/s not km/s), multiply all kernels (including eta)
    #       by 1e3.  Even though MINEOS requires SI input, the kernel output
    #       assumes seismological (km/s) units!
    vsv = kernels.vsv[kernels.period == period]

    if kernels['type'].iloc[0] == 'Rayleigh':#isinstance(kernel, mineos.RayleighKernels):
        vsh = np.zeros_like(vsv)
        vpv = kernels.vpv[kernels.period == period]
        vph = kernels.vph[kernels.period == period]
        eta = kernels.eta[kernels.period == period]

    if kernels['type'].iloc[0]  == 'Love':#isinstance(kernel, mineos.LoveKernels):
        vsh = kernels.vsh[kernels.period == period]
        vpv = np.zeros_like(vsv)
        vph = np.zeros_like(vsv)
        eta = np.zeros_like(vsv)

    return np.hstack((vsv, vsh, vpv, vph, eta))

def _convert_to_model_kernels(depth:np.array,
                              model:define_models.InversionModel):
    """ Convert from Frechet kernels as function of v(z) to function of p.

    The Frechet kernels from MINEOS are given at the same depths as those in
    the MINEOS model card, as a function of the model card v(z).  However, we
    want to invert for a model in a different format, p, so we need to adjust
    the kernels accordingly.

    Let   m:    old model, as a function of depth, from MINEOS card
                multiple parameters - [vsv, vsh, vpv, vph, eta]
          p:    new model
                multiple parameters - [s, t]
          c:    observed phase velocities, Love stacked on top of Rayleigh

    The MINEOS kernels are a matrix of dc/dm
        i.e.   dc_0/dvsv_0, ..., dc_0/dvsv_M, dc_0/dvsh_0, ..., dc_0/deta_M
            [       :     ,  : ,      :     ,      :     ,  : ,      :      ]
                dc_N/dvsv_0, ..., dc_N/dvsv_M, dc_N/dvsh_0, ..., dcN_deta_M

    We want a matrix of dc/dp
        i.e.   dc_0/ds_0, ..., dc_0/ds_P, dc_0/dt_0, ..., dc_0/dt_D
            [       :   ,  : ,    :     ,    :     ,  : ,    :      ]
               dc_N/ds_0, ..., dc_N/ds_P, dc_N/dt_0, ..., dc_N/dt_D


    As dx/dy = dx/da * da/dy, we need to find the matrix dm/dp
        i.e.   dvsv_0/ds_0, ..., dvsv_0/ds_P, dvsv_0/dt_0, ..., dvsv_0/dt_D
                    :     ,  : ,    :       ,    :       ,  : ,    :
            [  dvsv_M/ds_0, ..., dvsv_M/ds_P, dvsv_M/dt_0, ..., dvsv_M/dt_D  ]
               dvsh_0/ds_0, ..., dvsh_0/ds_P, dvsh_0/dt_0, ..., dvsh_0/dt_D
                    :     ,  : ,    :       ,    :       ,  : ,    :
               deta_M/ds_0, ..., deta_M/ds_P, deta_M/dt_0, ..., deta_M/dt_D

    By matrix multiplication, this works out as
        e.g. dc_0/ds_0 = sum(dc_0/dm_a * dm_a/ds_0)
    where the sum is from a = 0 to a = N.

    A lot of these partial derivatives (dm_a/dp_b) will be zero,
    e.g. for values of vsv, vsh, vpv, vph that are far from the value of s
         or t that is being varied; eta is held constant and never dependent
         on our model parameters [s, t].
    The ones that are non-zero are calculated differently depending on where
    the depth point at which m_a is defined (z_a) is compared to the depth
    of the model parameter, p_b, that is being varied.  So we will call
    different functions to build the partial derivatives in the layer
    above p_b, the layer below p_b (and, when we are varying t, the layer two
    layers below p_b, i.e. the layer below the boundary layer).

    Given that s is just Vsv defined at a number of points in depth, we can find
    the partial derivatives of the other velocities (vsh, vpv, vph) by
    scaling between them.

    Arguments:
        depth:
            - (n_card_depths, ) np.array
            - Units:    kilometres
            - Depth vector for MINEOS kernel.
        model:
            - define_models.InversionModel
            - Units:    seismological (i.e. vsv in km/s, thickness in km)
            - Remember that the field boundary_inds contains the indices of
              the boundaries that we are inverting the depth/width of.  So if
              i_b is the first of these boundary_inds,
                model.vsv[i_b]: Vsv at the top of the layer
                model.vsv[i_b + 1]: Vsv at the bottom of the layer
                model.thickness[i_b]: thickness of the layer above the boundary
                    (controls the depth of the boundary layer)
                np.sum(model.thickness[:i_b + 1]): depth of the top of the
                    boundary layer (i.e. up to and including thickness[i_b])
                model.thickness[i_b + 1]: width of the boundary layer itself
            - Remember that, for a given inversion, we are fixing the width
              of the boundary layer and only varying the depth to the top of
              of the boundary layer.
                i.e.    t = model.thickness[model.boundary_inds]

    Returns:
        dm_dp_mat:
            - (n_MINEOS_model_points,
               n_inversion_model_depths + n_boundary_layers) np.array
            - Units:    seismological (i.e. vsv in km/s, thickness in km)
            - This is dm/dp, where p = [s; t], s = vsv defined at a series of
              depth points and t = the thickness of the layer overlying a
              boundary layer (and thus controlling its depth), and m is the
              model that corresponds to the MINEOS kernels.


    """

    dm_ds_mat = _calculate_dm_ds(model, depth)
    dm_dt_mat = _calculate_dm_dt(model, depth)
    dm_dp_mat = np.hstack((dm_ds_mat, dm_dt_mat))

    return dm_dp_mat


def _calculate_dm_ds(model:define_models.InversionModel,
                     depth:np.array):
    """

    To convert the MINEOS kernels (dc/dm) to inversion model kernels (dc/dp),
    we need to define the matrix dm/dp (dc/dp = dc/dm * dm/dp).  We divide
    our inversion model, p, into two parts: the defined velocities at various
    depths (s) and the depth and thickness of certain boundary layers of
    interest (t).

    Here, we calculate dm/ds for the model card points above (shallower than)
    the boundary layer.  In the following description, I'm replacing subscripts
    with underscores - everything before the next space should be subscripted.
    e.g. y_i+1 is the 'i+1'th value of y.

    We can define the model card Vsv (m = v(z)) in terms of s as follows:
      - For every point s_i, we define the depth of that point, y_i, as the
        sum of the thicknesses above it: np.sum(thickness[:i + 1])
            (Remember model.thickness[i] is the thickness of the layer ABOVE
             the point where model.vsv[i] is defined)
      - For any depth, z_a, find b s.t. y_b <= z_a < y_b+1
            (Remember that v(z) is just linearly interpolated between s values)
      - Can then define v_a as
            v_a = s_b + (s_b+1 - s_b)/(y_b+1 - y_b) * (z_a - y_b)
      - Note that if z_a == y_b, then v_a == s_b

    Depending on whether we are above or below the change in Vs affects the
    partial derivative, as the original gradient is dependent on the adjacent
    values of velocity.

    We therefore call distinct (_convert_kernels_d[shallow|deep]er_by_d_s)
    functions to cover z points above and below the node in y.  We do this by
    looping through y (i.e. the depth points in the inversion model), and
    calling functions to fill in the partials directly above and below this
    node in y.  These called functions find all of the nodes in z (i.e. the
    depth points in the MINEOS model) that will be affected by the change at y,
    and loop through them - thus calculating dm/ds one value at a time, first
    looping by ds (i = 0:n_layers) then looping by dm (N = d_inds, where these
    are the indices of z that will be affected by the change at y_i). Therefore,
    each of these function calls will fill some of a single column of dm_ds_mat
    ([dm_0/ds_i; ...; dm_N/ds_i]), although most of these values will be zero.

    """
    n_layers = model.vsv.size - 1 # last value of s is pinned (not inverted for)
    dm_ds_mat = np.zeros((depth.size, n_layers))

    # Do dm/ds column by column
    # Build first column, dm/ds_0 - only affects layers deeper than s_0
    dm_ds_mat = _convert_kernels_d_deeperm_by_d_s(model, 0, depth, dm_ds_mat)
    # Build other columns, dc/ds_i
    for i in range(1, n_layers):
        dm_ds_mat = _convert_kernels_d_shallowerm_by_d_s(
            model, i, depth, dm_ds_mat
        )
        dm_ds_mat = _convert_kernels_d_deeperm_by_d_s(
            model, i, depth, dm_ds_mat
        )

    return dm_ds_mat


def _calculate_dm_dt(model:define_models.InversionModel,
                     depth:np.array):
    """
        To convert the MINEOS kernels (dc/dm) to inversion model kernels (dc/dp),
        we need to define the matrix dm/dp (dc/dp = dc/dm * dm/dp).  We divide
        our inversion model, p, into two parts: the defined velocities at various
        depths (s) and the depth and thickness of certain boundary layers of
        interest (t).

        Here, we calculate dm/dt for the model card points above (shallower than)
        the boundary layer.  In the following description, I'm replacing subscripts
        with underscores - everything before the next space should be subscripted.
        e.g. y_i+1 is the 'i+1'th value of y.

        The values, t_i, in the model, p, have slightly confusing effects on v(z)
        because we have to go via the effect on s, the velocities defined in p.
        Let's define ib, the index in s that corresponds to the index i in t.
            ib = model.boundary_inds[i]
        Note that ib-1, ib+1, etc are adding to the indices in s, not in t.
        Let's also define y_ib, the depth of s_ib; d_i, the depth of t_i;
        w_i, the width of the boundary layer.
            y_ib = d_i = y_ib-1 + t_i
            y_ib+1 = d_i + w_i = y_ib-1 + t_i + w_i
        We want to keep the width of the boundary layer, w_i, constant throughout
        a single inversion.  Otherwise, we want to pin the absolute depths, y, of
        all other points in s.  That is, other than y_ib and y_ib+1 for each t_i,
        the depths, y, are immutable.  However, changing these depth points changes
        the velocity gradient on either side of them.  Therefore, changing t_i will
        affect velocities between y_ib-1 < z_a < y_ib+2 (note not inclusive!).

        We can define the model card Vsv (m = v(z)) in terms of t as follows:
          - Each point t_i refers to the thickness of the layer above a boundary
            layer, model.thickness[model.boundary_inds[i]]
          - For every point t_i, we define the depth of that point, d_i, as the
            sum of the thicknesses above it:
                np.sum(model.thickness[:model.boundary_inds[i] + 1])
                = np.sum(model.thickness[:model.boundary_inds[i]]) + t_i
          - As above, we've defined y_ib, y_ib+1, etc
          - For any depth, z_a, try to find b s.t. y_b < z_a < y_b+1
            CONDITIONAL ON this being in the depth range y_ib-1 < z_a < y_ib+2
                (There may be no such z_a if these z points fall outside of the
                depth range of interest for this boundary layer, i)
          - Can then define v_a as
                v_a = s_b + ((s_b+1 - s_b) / (y_b+1 - y_b) * (z_a - y_b))

    As for _calculate_dm_ds(), we loop through the values of t in this function
    to call other functions that calculate the partial derivative based on the
    relative position of the affected z points to the altered depth -
    immediately above the boundary layer, within the boundary layer, and
    immediately below the boundary layer.  Each of these called functions
    then loops through the relevent points in z - passing the index of the
    altered value of t, i, in as an argument.  This fills some of a single
    column of dm_dt_mat ([dm_0/dt_i; ...; dm_N/dt_i]), although most of these
    values will be zero.
    """

    dm_dt_mat = np.zeros((depth.size, model.boundary_inds.size))

    # Now, do dm/dt column by column
    for i in range(model.boundary_inds.size):
        dm_dt_mat = _convert_kernels_d_shallowerm_by_d_t(
            model, i, depth, dm_dt_mat
        )
        dm_dt_mat = _convert_kernels_d_withinboundarym_by_d_t(
            model, i, depth, dm_dt_mat
        )
        dm_dt_mat = _convert_kernels_d_deeperm_by_d_t(
            model, i, depth, dm_dt_mat
        )

    return dm_dt_mat

def _convert_kernels_d_shallowerm_by_d_s(model:define_models.InversionModel,
                                         i:int, depth:np.array,
                                         dm_ds_mat:np.array):
    """ Find dm/ds for the model card points above the boundary layer.

    Here, we are looking specifically at the values of m that are shallower than
    the s point in question, s_i, that will still be affected by a change to
    s_i - that is, the values of z between y_i-1 and y_i.  So i = b+1 in the
    equation in the _calculate_dm_ds docstring.
            v_a = s_i-1 + (s_i - s_i-1)/(y_i - y_i-1) * (z_a - y_i-1)

    In terms of the partial derivative:
            d(v_a)/d(s_i) = (z_a - y_i-1)/(y_i - y_i-1)

    Note that (y_i - y_i-1) is equivalent to thickness[i], the thickness of
    the layer above the point i.


    Arguments:
        model:
            - define_models.InversionModel
            - Units:    seismological (km/s and km)
            - Model in layout ready for easy conversion to column vector
              to be used in least squares inversion.
        i:
            - int
            - Units:    n/a
            - Index in InversionModel for which we are calculating the column
              of partial derivatives.
        depth:
            - (n_card_depths, ) np.array
            - Units:    kilometres
            - Depth vector for MINEOS kernel.
        dm_ds_mat:
            - (n_card_depths, n_inversion_model_depths) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/ds that we are filling in a bit
              at a time.

    Returns:
        dm_ds_mat:
            - (n_card_depths, n_inversion_model_depths) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/ds with a few more values filled
              in - specifically, those in the 'i'th column (for model parameter
              s_i) in rows corresponding to depths between y_i-1 and y_i.

    """
    # Find the layers in card depth, z, shallower than the depth where s_i is
    # defined, y_i, and deeper than the depth where s_i-1 is specified, y_i-1.
    # These are the points in z that will be affected by varying s_i
    y_i_minus_1 = np.sum(model.thickness[:i])
    y_i = np.sum(model.thickness[:i+1])

    d_inds, = np.where(np.logical_and(y_i_minus_1 < depth, depth <= y_i))

    for i_d in d_inds:
        dm_ds_mat[i_d, i] = ((depth[i_d] - y_i_minus_1)
                             /model.thickness[i])

    return dm_ds_mat

def _convert_kernels_d_deeperm_by_d_s(model, i, depth, dm_ds_mat):
    """ Find dm/ds for the model card points above the boundary layer.


    Here, we are looking specifically at the values of m that are deeper than
    the s point in question, s_i, that will still be affected by a change to
    s_i - that is, the values of z between y_i and y_i+1.  So i = b in the
    equation in the _calculate_dm_ds docstring.
            v_a = s_i + (s_i+1 - s_i)/(y_i+1 - y_i) * (z_a - y_i)

    In terms of the partial derivative:
            d(v_a)/d(s_i) = 1 - (z_a - y_i)/(y_i+1 - y_i)

    Note that (y_i+1 - y_i) is equivalent to thickness[i+1], the thickness of
    the layer below the point i.

    Arguments:
        model:
            - define_models.InversionModel
            - Units:    seismological (km/s and km)
            - Model in layout ready for easy conversion to column vector
              to be used in least squares inversion.
        i:
            - int
            - Units:    n/a
            - Index in InversionModel for which we are calculating the column
              of partial derivatives.
        depth:
            - (n_card_depths, ) np.array
            - Units:    kilometres
            - Depth vector for MINEOS kernel.
        dm_ds_mat:
            - (n_card_depths, n_inversion_model_depths) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/ds that we are filling in one
              bit at a time.

    Returns:
        dm_ds_mat:
            - (n_card_depths, n_inversion_model_depths) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/ds with a few more values filled
              in - specifically, those in the 'i'th column (for model parameter
              s_i) in rows corresponding to depths between y_i and y_i+1.
    """
    # Find h, the number of layers in card depth deeper than defined s point
    # that will be affected by varying that s
    y_i = np.sum(model.thickness[:i+1])
    y_i_plus_1 = np.sum(model.thickness[:i+2])

    d_inds, = np.where(np.logical_and(y_i <= depth, depth < y_i_plus_1))

    for i_d in d_inds:
        dm_ds_mat[i_d, i] = 1 - ((depth[i_d] - y_i)
                                 /model.thickness[i+1])

    return dm_ds_mat

def _convert_kernels_d_shallowerm_by_d_t(model:define_models.InversionModel,
                                         i:int, depth:np.array,
                                         dm_dt_mat:np.array) -> np.array:
    """ Find dm/dt for the model card points above the boundary layer.

    Here, we are looking specifically at the values of m that are shallower than
    the s point in question, s_ib, that will still be affected by a change to
    t_i - that is, the values of z between y_ib-1 and y_ib.  So b = ib-1
            v_a = s_ib-1 + ((s_ib - s_ib-1) / (y_ib - y_ib-1) * (z_a - y_ib-1))
            v_a = s_ib-1 + ((s_ib - s_ib-1) / t_i * (z_a - y_ib-1))

    In terms of the partial derivative:
            d(v_a)/d(t_i) = -(z_a - y_ib-1) * (s_ib - s_ib-1) / t_i**2


    Arguments:
        model:
            - define_models.InversionModel
            - Units:    seismological (km/s and km)
            - Model in layout ready for easy conversion to column vector
              to be used in least squares inversion.
        i:
            - int
            - Units:    n/a
            - Index in InversionModel for which we are calculating the column
              of partial derivatives.
        depth:
            - (n_card_depths, ) np.array
            - Units:    kilometres
            - Depth vector for MINEOS kernel.
        dm_dt_mat:
            - (n_card_depths, n_boundary_layers) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/dt that we are filling in a bit
              at a time.

    Returns:
        dm_dt_mat:
            - (n_card_depths, n_boundary_layers) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/dt with a few more values filled
              in - specifically, those in the 'i'th column (for model parameter
              t_i) in rows corresponding to depths between y_ib-1 and y_ib.

    """
    # s_ib is the velocity at the top of the boundary, model.boundary_inds[i]
    # s_ib_minus_1 is the velocity at the top of the model layer above this

    # model.thickness[i_b] is the thickness of the layer above the boundary
    # i.e. what we are inverting for; model.thickness[i_b + 1] is the thickness
    # of the boundary layer itself

    ib = model.boundary_inds[i]
    t_i = model.thickness[ib]

    y_ib_minus_1 = np.sum(model.thickness[:ib])
    y_ib = np.sum(model.thickness[:ib + 1])

    d_inds, = np.where(np.logical_and(y_ib_minus_1 < depth, depth < y_ib))

    for i_d in d_inds:
        dm_dt_mat[i_d, i] = -(
            ((model.vsv[ib] - model.vsv[ib - 1]) * (depth[i_d] - y_ib_minus_1))
            / (t_i ** 2)
        )

    return dm_dt_mat

def _convert_kernels_d_withinboundarym_by_d_t(
        model:define_models.InversionModel, i:int, depth:np.array,
        dm_dt_mat:np.array) -> np.array:
    """ Find dm/dt for the model card points within the boundary layer.

    Here, we are looking specifically at the values of m that are within the
    boundary layer in question - that is, the values of z between y_ib and
    y_ib+1.  So ib = b in the equation above.
            v_a = s_ib + ((s_ib+1 - s_ib) / (y_ib+1 - y_ib) * (z_a - y_ib))
            v_a = s_ib + ((s_ib+1 - s_ib) / w_i * (z_a - (y_ib-1 + t_i)))

    In terms of the partial derivative:
            d(v_a)/d(t_i) = -(s_ib+1 - s_ib) / w_i

    Arguments:
        model:
            - define_models.InversionModel
            - Units:    seismological (km/s and km)
            - Model in layout ready for easy conversion to column vector
              to be used in least squares inversion.
        i:
            - int
            - Units:    n/a
            - Index in InversionModel for which we are calculating the column
              of partial derivatives.
        depth:
            - (n_card_depths, ) np.array
            - Units:    kilometres
            - Depth vector for MINEOS kernel.
        dm_dt_mat:
            - (n_card_depths, n_boundary_layers) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/dt that we are filling in a bit
              at a time.

    Returns:
        dm_dt_mat:
            - (n_card_depths, n_boundary_layers) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/dt with a few more values filled
              in - specifically, those in the 'i'th column (for model parameter
              t_i) in rows corresponding to depths between y_ib-1 and y_ib.

    """

    ib = model.boundary_inds[i]
    w_i = model.thickness[ib + 1]

    y_ib = np.sum(model.thickness[:ib + 1])
    y_ib_plus_1 = np.sum(model.thickness[:ib + 2])

    # Assuming constant boundary layer width shifted up or down by some small dt
    # Therefore, all points in the boundary layer will be affected in the same
    # way, so the partial derivative is constant throughout the layer.
    # Note that we are assuming small dt, such that no depth point, z_a,
    # actually changes sides of a node in the new model parameterisation, p.
    d_inds, = np.where(np.logical_and(y_ib <= depth, depth < y_ib_plus_1))
    dm_dt_mat[d_inds, i] = -(
            (model.vsv[ib + 1] - model.vsv[ib])
            / w_i
    )

    return dm_dt_mat

def _convert_kernels_d_deeperm_by_d_t(model:define_models.InversionModel,
                                      i:int, depth:np.array,
                                      dm_dt_mat:np.array) -> np.array:
    """ Find dm/dt for the model card points below the boundary layer.

    Here, we are looking specifically at the values of m that are deeper than
    the boundary layer in question, s_ib, that will still be affected by a
    change to t_i - that is, the values of z between y_ib+1 and y_ib+2.
    So, from the equation above, sub in b = ib+1
            v_a = s_ib+1
                  + ((s_ib+2 - s_ib+1) / (y_ib+2 - y_ib+1) * (z_a - y_ib+1))
            v_a = s_ib+1
                  + ((s_ib+2 - s_ib+1) / (y_ib+2 - (y_ib-1 + t_i + w_i)
                     * (z_a - (y_ib-1 + t_i + w_i)))

    In terms of the partial derivative (via the chain rule & product rule):
            d(v_a)/d(t_i) = ((s_ib+2 - s_ib+1) * (z_a - y_ib+2))
                            / (t_i - y_ib+2 + y_ib-1 + w_i)**2

    DERIVATION BREAK
    For the purposes of deriving this, let's simplify terms a little bit.
        a = s_ib+2 - s_ib+1
        b = z_a - y_ib-1 - w_i
        c = y_ib+2 - y_ib-1 - w_i
        x = t_i

    Our equation is now
        d(v_a)/dx = d/dx (s_ib+1 + a * (b-x) / (c-x))
                  = d/dx (a/(c-x) * (b-x)/(c-x))
                  = d/dx (ab/(c-x) - ax/(c-x))

    The chain rule is d/dx (f(g(x)) = f'(g(x))g'(x))
        d/dx (ab/(c-x)):     g(x) = c-x      g'(x) = -1
                             f(y) = ab/y     f'(y) = -ab/y**2
        d/dx (ab/(c-x)) = ab/(c-x)**2

    The product rule is d/dx (h(x)j(x)) = h'(x)j(x) + h(x)j'(x)
        d/dx (-ax/(c-x)):   h(x) = -ax      h'(x) = -a
                            j(x) = 1/(c-x)  j'(x) = -1/(c-x)**2
        d/dx (-ax/(c-x)) = -a/(c-x) + ax/(c-x)**2
                         = (-a(c-x) + ax)/(c-x)**2
                         = -ac/(c-x)**2

    The total derivative is therefore
        d(v_a)/dx = ab/(c-x)**2 - ac/(c-x)**2
                  = a(b-c)/(c-x)**2
                  = a(b-c)/(x-c)**2

                  = (s_ib+2 - s_ib+1) * (z_a - y_ib+2)
                    / (t_i - y_ib+2 + y_ib-1 + w_i)**2

    BACK TO THE REAL DOCSTRING


    Arguments:
        model:
            - define_models.InversionModel
            - Units:    seismological (km/s and km)
            - Model in layout ready for easy conversion to column vector
              to be used in least squares inversion.
        i:
            - int
            - Units:    n/a
            - Index in InversionModel for which we are calculating the column
              of partial derivatives.
        depth:
            - (n_card_depths, ) np.array
            - Units:    kilometres
            - Depth vector for MINEOS kernel.
        dm_dt_mat:
            - (n_card_depths, n_boundary_layers) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/dt that we are filling in a bit
              at a time.

    Returns:
        dm_dt_mat:
            - (n_card_depths, n_boundary_layers) np.array
            - Units:    assumes seismological (km/s, km)
            - Partial derivative matrix of dm/dt with a few more values filled
              in - specifically, those in the 'i'th column (for model parameter
              t_i) in rows corresponding to depths between y_ib-1 and y_ib.

    """
    # s_ib_minus_1 is the velocity at the top of the model layer above this
    # s_ib is the velocity at the top of the boundary, model.boundary_inds[i]
    # s_ib_plus_1 is the velocity at the bottom of the boundary
    # s_ib_plus_2 is the velocity at the bottom of the layer below the boundary
    # ((s_ib+2 - s_ib+1) * (z_a - y_ib+2))
    #                 / (t_i - y_ib+2 + y_ib-1 + w_i)**2

    ib = model.boundary_inds[i]
    t_i = model.thickness[ib]
    w_i = model.thickness[ib + 1]

    y_ib_minus_1 = np.sum(model.thickness[:ib])
    y_ib_plus_1 = np.sum(model.thickness[:ib + 2])
    y_ib_plus_2 = np.sum(model.thickness[:ib + 3])

    d_inds, = np.where(np.logical_and(y_ib_plus_1 <= depth, depth < y_ib_plus_2))

    for i_d in d_inds:
        dm_dt_mat[i_d, i] = (
            (model.vsv[ib + 2] - model.vsv[ib + 1]) * (depth[i_d] - y_ib_plus_2)
            / ((t_i - (y_ib_plus_2 - y_ib_minus_1 - w_i)) ** 2)
        )

    return dm_dt_mat

def _scale_dvsv_dp_to_other_variables(dvsv_dp_mat:np.array,
                                      setup_model:define_models.SetupModel):
    """ Use scaling relatioships in setup_model to define other partials.

    Here, we assume that there is a constant Vsv/Vsh, Vpv/Vph, Vpv/Vsv, eta.
    This allows us to construct a full dm/dp matrix by just scaling up the
    values that we have calculated for dvsv/dp.

        d(c) / d(p)  = d(c) / d(other) * d(other) / d(vsv) * d(vsv) / d(p)

    Given we scale linearly between Vsv and all the other velocities
    (Vsh, Vpv, Vph),        other = constant * vsv
                            d(other) / d(vsv) = constant

    For eta, as we fix this to be constant,     d(other) / d(vsv) = 0.

    Given these simplistic assumptions (for now!?), this is a super easy vstack.
    The G_MINEOS is ordered (vsv, vsh, vpv, vph, eta).
    """

    return np.vstack((
                dvsv_dp_mat,
                dvsv_dp_mat / setup_model.vsv_vsh_ratio,
                dvsv_dp_mat * setup_model.vpv_vsv_ratio,
                dvsv_dp_mat
                    * setup_model.vpv_vsv_ratio / setup_model.vpv_vph_ratio,
                np.zeros_like(dvsv_dp_mat)
    ))