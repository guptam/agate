#!/usr/bin/env python
# pylint: disable=W0212

import leather

from agate import utils


def line_chart(self, x=0, y=1, path=None, width=None, height=None):
    """
    Render a line chart using :class:`leather.Chart`.

    :param x:
        The name or index of a column to plot as the x-axis. Defaults to the
        first column in the table.
    :param y:
        The name or index of a column to plot as the y-axis. Defaults to the
        second column in the table.
    :param path:
        If specified, the resulting SVG will be saved to this location. If
        :code:`None` and running in IPython, then the SVG will be rendered
        inline. Otherwise, the SVG data will be returned as a string.
    :param width:
        The width of the output SVG.
    :param height:
        The height of the output SVG.
    """
    chart = leather.Chart()
    chart.add_x_axis(name=x)
    chart.add_y_axis(name=y)
    chart.add_line(self, x=x, y=y)

    return chart.to_svg(path=path, width=width, height=height)
