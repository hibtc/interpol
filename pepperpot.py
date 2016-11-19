"""
Simple analysis utility for some pepperpot data.

Usage:
    pepperpot interpol zeros INPUT OUTPUT [-r RADIUS] [-i SHAPE] [-z SHAPE]
    pepperpot interpol gauss INPUT OUTPUT [-r RADIUS] [-i SHAPE] [-w WIDTH]
    pepperpot interpol arith INPUT OUTPUT [-r RADIUS] [-i SHAPE]
    pepperpot generate INPUT [OUTPUT] [-n NUM] [-p PPP] [-g SHAPE]
    pepperpot plot gauss INPUT [OUTPUT] [-r RADIUS] [-g SHAPE]
    pepperpot plot point INPUT [OUTPUT] [-r RADIUS]
    pepperpot plot pdist INPUT [OUTPUT]
    pepperpot info INPUT
    pepperpot (-h | -v)

Arguments:
    INPUT

Interpolation options:
    -r RADIUS, --radius RADIUS      Radius for averaging [default: 2,2,4,4]
    -i SHAPE, --igrid SHAPE         Interpolation grid shape [default: 25]
    -z SHAPE, --zgrid SHAPE         Zero (helper) grid shape [default: 15]
    -w WIDTH, --width WIDTH         Decay width [default: 1]

Particle generation options:
    -n NUM, --number NUM            Number of particles to generate [default: 500]
    -p FILE, --pepperpot FILE       Pepperpot file for normalizing the grid size
    -g SHAPE, --grid SHAPE          Generate grid shape [default: 25]

Plot options:
    grid                            Plot grid shape [default: 25]
    radius                          Point radius [default: 2,2,4,4]

Interpolation commands:
    zeros       Add zeros based on proximity interpolate using `griddata`
    gauss       Gaussian average
    arith       Arithmetic average

Interpolation arguments:
    INPUT       Pepperpot measurements (.ppp)
    OUTPUT      Probability distribution (.npy)

Particle generation arguments:
    INPUT       Probability distribution (.npy)
    OUTPUT      Particles list (.txt)

Plot commands:
    gauss       Plot a scaled normal distribution around each point
    point       Simple scatter plot
    pdist       Plot a 2D probability distribution

Plot arguments:
    INPUT       Pepperpot (.ppp) or probability distribution (.npy)
    OUTPUT      Plot file (.pdf)
"""

from __future__ import absolute_import
from __future__ import unicode_literals
from __future__ import division

import tempfile
import sys

import numpy as np
import scipy.spatial
import scipy.interpolate
import matplotlib.pyplot as plt

from mpl_toolkits.axes_grid1 import make_axes_locatable

from docopt import docopt

from util import trace
from interpol import (
    Grid, Box, far_points__weighted_cumulative,
    scatter, generate_particle_interpol,
    restrict_to_polytope,
    moving_average,
    gaussian_filter_local_exact,
)


COL_TITLES = ('x', 'y', 'px', 'py')
PLOTS_2D = ([0, 1], [0, 2], [1, 3],
            [2, 3], [0, 3], [1, 2])


def get_columns(array, columns):
    if isinstance(columns, list):
        block = array[columns]
        return block.view(np.float64).reshape(block.shape + (-1,))
    else:
        return array[columns]


def scalar_or_vector(value, parse):
    if ',' in value:
        return np.array([parse(x) for x in value.split(',')])
    return parse(value)


def savefig(fig, filename):
    if filename:
        fig.savefig(filename, bbox_inches='tight')
    else:
        fig.show()


def read_ppp(in_file):
    rawdata = np.genfromtxt(in_file, names=True)
    points = get_columns(rawdata, ['x', 'y', 'xprime', 'yprime'])
    values = get_columns(rawdata, 'weight')
    return points, values


def interpolate_pdist(points, values, widths, igrid, zgrid, radius):
    with trace("Computing zeros"):
        zero_points = far_points__weighted_cumulative(
            zgrid, points, values, widths, radius)
    print("  Number of zero points: {}".format(len(zero_points)))

    with trace("Restricting to convex hull"):
        hull = scipy.spatial.ConvexHull(np.array(points))
        zero_points = restrict_to_polytope(hull.equations, zero_points)
    print("  Relative hull volume: {}".format(hull.volume / zgrid.box.volume))
    print("  Selected zero points: {}".format(len(zero_points)))

    with trace("Interpolating 4D probability distribution"):
        zero_values = np.zeros(len(zero_points))
        pdist = scipy.interpolate.griddata(
            np.vstack((points, zero_points)),
            np.hstack((values, zero_values)),
            igrid.xi(), fill_value=0)
        return pdist.reshape(igrid.shape)


def save_pdist(pdist, out_file=None, method=''):
    """Save a probability distribution matrix to a file."""
    if out_file is None:
        out_file = tempfile.mktemp(prefix='pdist_{}_'.format(method), dir='.')
    with trace("Saving probability distribution to: {}".format(out_file)):
        np.save(out_file, pdist)


def plot_2d_projections(message, func, box_4d=None, filename=None,
                        width=0.7, height=0.5, hspace=0.1, vspace=0.1):
    fig = plt.figure()
    with trace(message):
        for i, comb in enumerate(PLOTS_2D):
            title = '{}/{}'.format(*(COL_TITLES[c] for c in comb))
            # compute image data
            image = np.array(func(comb))
            # add axes
            row, col = i // 3, i % 3
            ax = fig.add_axes([
                col*(width-hspace),
                row*(height+vspace),
                width, height])
            ax.set_title(title)
            # plot image
            extent = box_4d and box_4d.projection(comb).lrbt()
            im = ax.imshow(image, extent=extent, cmap="viridis")
            # add colorbar that fits the image size
            divider = make_axes_locatable(ax)
            cax = divider.append_axes("right", size="5%", pad=0.05)
            fig.colorbar(im, orientation='vertical', cax=cax)
    savefig(fig, filename)


def plot_gauss_sum(grid_4d, points, values, widths, radius_4d, filename):
    """Plot the 2D projections of a 4D particle scatter."""
    def gauss(comb):
        ppoints = points[:,comb]
        pgrid = Grid(grid_4d.box.projection(comb), grid_4d.shape[comb])
        data = scatter(pgrid, ppoints, values, widths, radius_4d[comb])
        return data / np.max(data)
    plot_2d_projections(
        'Gaussian sum "scatter" plot',
        gauss, grid_4d.box, filename)


def plot_pdist(pdist, filename):
    """Plot the 2D projections of a 4D probability distribution matrix."""
    all_axes = set(range(4))
    def plot_pdist(comb):
        data = np.sum(pdist, axis=tuple(all_axes - set(comb)))
        return data / np.max(data)
    plot_2d_projections(
        'Plotting probability distribution',
        gauss, None, filename)


def plot_scatter(points, radius, filename):
    plt.clf()
    with trace("Plotting particle scatter"):
        for i, comb in enumerate(PLOTS_2D):
            title = '{}/{}'.format(*(COL_TITLES[c] for c in comb))
            ax = plt.subplot(2, 3, i+1)
            ax.set_title(title)
            x, y = points[:,comb].T
            plt.scatter(x, y, radius)
    savefig(plt, filename)


def main(args=None):
    opts = docopt(__doc__, args)
    if opts['interpol']:
        interpol_main(opts)
    elif opts['generate']:
        generate_main(opts)
    elif opts['plot']:
        plot_main(opts)
    elif opts['info']:
        info_main(opts)


def interpol_main(opts):

    points, values = read_ppp(opts['INPUT'])
    widths = float(opts['--width'])
    radius = scalar_or_vector(opts['--radius'], float)
    igrid_shape = scalar_or_vector(opts['--igrid'], int)
    zgrid_shape = scalar_or_vector(opts['--zgrid'], int)

    # grid for interpolation:
    data_box = Box.from_points(points)
    igrid = Grid(data_box, igrid_shape)

    methods = ['zeros', 'arith', 'gauss']
    for method in methods:
        if opts[method]:
            break

    if method == 'zeros':
        zgrid = Grid(data_box, zgrid_shape)
        pdist = interpolate_pdist(points, values, widths, igrid, zgrid, radius)

    elif method == 'arith':
        pdist = moving_average(
            igrid, points, values, widths, radius)

    elif method == 'gauss':
        pdist = gaussian_filter_local_exact(
            igrid, points, values, widths, radius)

    save_pdist(pdist, opts['OUTPUT'], method)


def generate_main(opts):
    pdist = np.load(opts['INPUT'])
    shape = scalar_or_vector(opts['--grid'], int)
    count = int(opts['--number'])
    with trace("Generating {} particles".format(count)):
        particles = np.array([
            generate_particle_interpol(pdist, shape)
            for i in range(count)
        ])
    if opts['--pepperpot']:
        points, values = read_ppp(opts['--pepperpot'])
        box = Box.from_points(points)
        scale = box.size / (np.array(shape) * np.array(pdist.shape))
        particles = particles * scale + box.min_bound

    particles = np.hstack((particles, np.ones((len(particles), 1))))

    output = opts['OUTPUT'] or sys.stdout
    np.savetxt(output, particles,
               header='x y xprime yprime weight')


def plot_main(opts):
    if opts['gauss']:
        plot_gauss_main(opts)
    elif opts['point']:
        plot_point_main(opts)
    elif opts['pdist']:
        plot_pdist_main(opts)


def plot_gauss_main(opts):
    points, values = read_ppp(opts['INPUT'])
    widths = 1
    radius = scalar_or_vector(opts['--radius'], float)
    shape = scalar_or_vector(opts['--grid'], int)
    bounds = Box.from_points(points)
    grid = Grid(bounds, shape)
    plot_gauss_sum(grid, points, values, widths, radius, opts['OUTPUT'])


def plot_point_main(opts):
    points, values = read_ppp(opts['INPUT'])
    radius = scalar_or_vector(opts['--radius'], float)
    plot_scatter(points, radius, opts['OUTPUT'])


def plot_pdist_main(opts):
    pdist = np.load(opts['INPUT'])
    plot_pdist(pdist, opts['OUTPUT'])


def info_main(opts):
    points, values = read_ppp(opts['INPUT'])
    box = Box.from_points(points)
    print("Min:  {}".format(box.min_bound))
    print("Max:  {}".format(box.max_bound))
    print("Size: {}".format(box.size))


if __name__ == '__main__':
    main(sys.argv[1:])
