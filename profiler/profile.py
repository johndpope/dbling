#!/usr/bin/env python3
"""
The case study script for the DFRWS paper.

Command line::

 Usage: profile.py [options] -d DFXML_FILE
        profile.py [options] -m MOUNT_POINT

 Options:
  -v   Verbose mode. Changes logging mode from INFO to DEBUG.
  -g   Show graph before searching for matches.
  -o MERL   Output results to the file MERL.
  --plain   Output results in a plain format instead of XML.


As a reminder, the command to mount an image is::

 sudo mount -o ro,noload -t <fs_type> <img_file> </mount/point>
"""
import logging
import sys
from datetime import datetime
from os import geteuid, seteuid
from os.path import abspath, dirname, join

from docopt import docopt
from graph_tool.topology import shortest_distance

try:
    from merl import Merl
except ImportError:
    sys.path.append(join(dirname(abspath(__file__)), '..'))
    from merl import Merl
from profiler.graph_diff import FilesDiff, init_logging


MAX_DIST = 2**31 - 1  # 2147483647  # Assumes the distance PropertyMap will be of type int32


def go(start, mounted=False, verbose=False, show_graph=False, output_file=None, plain=False):
    """Initiate the test.

    :param str start: Either the path to the mount point of the image or the
        path to the DFXML file of the image.
    :param bool mounted: Flag indicating if ``start`` is mounted, which is
        triggered when the ``-m`` option is given. Flag is `False` when the
        ``-d`` option is given.
    :param bool verbose: Flag that changes the logging mode from ``INFO`` to
        ``DEBUG``.
    :param bool show_graph: Show the graph before searching for matches. Set
        when the ``-g`` option is given.
    :param str output_file: Path to a file where the results are saved.
    :param bool plain: When set (using the ``--plain`` option), the results
        saved to ``output_file`` will not be in a MERL (XML) format.
    :rtype: None
    """
    init_logging(verbose=verbose)
    file_needs_closing = False
    if plain and output_file is None:
        output_file = 'profile_{}.{}'.format(datetime.now().strftime('%Y-%m-%d_%H-%M-%S'),
                                             'txt' if plain else 'merl')
        print('No output file specified for {} format. Saving to {}'.
              format('plain' if plain else 'MERL', output_file))
        output_file = open(output_file)
        file_needs_closing = True
    merl = Merl(out_fp=output_file, plain_output=plain)
    graph = FilesDiff()
    if mounted:
        try:
            euid = geteuid()
            if euid != 0:
                seteuid(0)
        except PermissionError:
            msg = 'Must have root privileges to read from a mount point.'
            logging.critical(msg)
            print('\n%s\n' % msg)
            raise
        graph.add_from_mount(start)
    else:
        graph.add_from_file(start)
    graph.trim_unuseful(True)
    if show_graph:
        graph.show_graph()
    # return
    candidates = extract_candidates(graph.graph_copy())
    # for c in candidates:
    #     graph.show_graph(c)

    logging.info('Searching the DB for matches for each candidate graph. (%d)' % len(candidates))
    merl.match_candidates(candidates)

    # Save XML to file, but only if the user didn't request output in a plain format
    if output_file is not None and not plain:
        merl.save_merl()

    merl.close_db()

    if file_needs_closing:
        output_file.close()

    logging.info('Search complete. Exiting.')


def extract_candidates(orig_graph):
    """
    Return a list of graph objects, each a candidate graph.

    :param orig_graph: The original graph made from the DFXML.
    :type orig_graph: common.graph.DblingGraph
    :return: List of candidate graph objects.
    :rtype: list
    """
    candidates = []
    # Stop iterating when we've emptied the original graph
    while orig_graph.num_vertices() > 0:
        sub_graph = orig_graph.copy()

        sg_vertices = get_subtree_vertices(sub_graph)

        # Remove all vertices in the subgraph from the original graph
        rm_list = []
        for v in orig_graph.vertices():
            if v in sg_vertices:
                rm_list.append(v)
        orig_graph.remove_vertex(rm_list)

        # Remove all vertices not in the list
        rm_list = []
        for v in sub_graph.vertices():
            if v not in sg_vertices:
                rm_list.append(v)
        sub_graph.remove_vertex(rm_list)

        # Add the subgraph to the list of candidates
        if sub_graph.num_vertices():
            # Must have at least one vertex to be of interest to us
            candidates.append(sub_graph)
            if not len(candidates) % 5:
                logging.debug('Extracted candidate graph %d' % len(candidates))

    return candidates


def get_subtree_vertices(g):
    """
    Return a list of all vertices connected to node.

    :param g: The graph from which to extract a subgraph.
    :type g: common.graph.DblingGraph
    :return: The list of all vertices in a subgraph of g.
    :rtype: list
    """

    # Get the shortest distance from the first vertex in the graph and everything else
    dist = shortest_distance(g, g.vertex(0), directed=False)

    l = []
    for i, v in enumerate(dist.a):
        # If the calculated distance is the max, assume it is infinite (not reachable), i.e. not part of the same
        # subgraph.
        if v < MAX_DIST:
            l.append(g.vertex(i))

    return l


if __name__ == '__main__':
    args = docopt(__doc__)
    params = dict(
        start=args['MOUNT_POINT'] if args['-m'] else args['DFXML_FILE'] if args['-d'] else None,
        mounted=args['-m'],
        verbose=args['-v'],
        show_graph=args['-g'],
        plain=args['--plain']
    )

    if args['-o'] is not None:
        with open(args['-o'], 'w') as fout:
            go(output_file=fout, **params)
    else:
        go(**params)
