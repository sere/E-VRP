#!/usr/bin/env python3
# coding: utf-8

""" E-VRP is a project about the routing of a fleet of electrical vehicles.

    E-VRP is a project developed for the Application of Operational Research
    exam at University of Modena and Reggio Emilia.

    Copyright (C) 2017  Serena Ziviani, Federico Motta

    This file is part of E-VRP.

    E-VRP is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    any later version.

    E-VRP is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with E-VRP.  If not, see <http://www.gnu.org/licenses/>.
"""

__authors__ = "Serena Ziviani, Federico Motta"
__copyright__ = "E-VRP  Copyright (C)  2017"
__license__ = "GPL3"

# -------------------------------- SCRIPT RUN ------------------------------- #
if __name__ != '__main__':
    print('Please do not load that script, run it!')
    exit(1)

# Add to the following loop every external library used!
for lib in ('matplotlib.pyplot as plt', 'networkx as nx', 'yaml'):
    try:
        exec('import ' + str(lib))
    except ImportError:
        print('Could not import {} library, please install it!'.format(lib))
        exit(1)

import math
import matplotlib.pyplot as plt
import networkx as nx
import os
import warnings
import yaml

import IO
import utility

utility.check_python_version()


def check_problem_solvability(graph):
    """Test if customers and stations are reachable from depot."""
    depot, customers, stations = None, list(), list()
    for node, data in graph.nodes_iter(data=True):
        if data['type'] == 'depot':
            depot = node
        elif data['type'] == 'customer':
            customers.append(node)
        elif data['type'] == 'station':
            stations.append(node)

    quit = False
    for cust in customers:
        if not nx.has_path(graph, depot, cust):
            IO.Log.warning('Customer {} is not reachable '
                           'from the depot'.format(cust))
            quit = True
        if not nx.has_path(graph, cust, depot):
            IO.Log.warning('Depot is not reachable '
                           'from customer {}'.format(cust))
            quit = True

    for stat in stations:
        if not any(nx.has_path(graph, x, stat) for x in [depot] + customers):
            IO.Log.warning('Refueling station {} is not reachable from any '
                           'customer or depot'.format(stat))
        if not any(nx.has_path(graph, stat, x) for x in [depot] + customers):
            IO.Log.warning('No customer or depot reachable from '
                           'refueling station {}'.format(stat))

    if quit:
        exit(1)


def check_workspace():
    """Ensure workspace exist and it contains only necessary files."""
    ws = utility.CLI.args().workspace
    if not os.path.isdir(ws):
        IO.Log.warning('Directory not found ({})'.format(ws))
        IO.Log.warning('Please set a correct workspace')
        exit(1)

    if not os.path.isfile(os.path.join(ws, 'edges.shp')):
        IO.Log.warning('edges.shp not found in workspace ({})'.format(ws))
        exit(1)

    if not os.path.isfile(os.path.join(ws, 'nodes.shp')):
        IO.Log.warning('nodes.shp not found in workspace ({})'.format(ws))
        exit(1)

    graph_read = nx.read_shp(path=os.path.join(ws, 'nodes.shp'), simplify=True)

    # check each node has an altitude attribute
    altitude = utility.CLI.args().altitude
    for node, data in graph_read.nodes_iter(data=True):
        if altitude not in data:
            IO.Log.warning('Could not find \'{}\' attribute in '
                           'nodes.shp'.format(altitude))
            exit(1)

        # check each altitude attribute is a floating point number
        if not isinstance(data[altitude], float):
            IO.Log.warning('Altitude of node lat: {}, lon {} is not a '
                           'float'.format(*node))
            exit(1)

    for f in os.listdir(ws):
        if f not in [prefix + suffix
                     for prefix in ('nodes.', 'edges.')
                     for suffix in ('dbf', 'shp', 'shx')]:
            IO.Log.warning('Please remove \'{}\''.format(os.path.join(ws, f)))
            exit(1)


def draw(graph):
    """Wrap networkx draw function and suppress its warnings."""
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=UserWarning)
        nx.draw(graph)
    plt.show()


def export_problem_to_directory():
    """Populate directory with a shapefile representation of the problem."""
    export_dir = utility.CLI.args().export_dir
    problem_file = utility.CLI.args().problem_file

    if not os.path.isfile(problem_file):
        IO.Log.warning('Problem file not found ({})'.format(problem_file))
        exit(1)

    if not os.path.isdir(export_dir):
        os.makedirs(export_dir)

    with open(problem_file, 'r') as f:
        problem = yaml.load(f)

    temp_graph = nx.DiGraph()
    temp_graph.add_node((problem['depot']['latitude'],
                         problem['depot']['longitude']))
    nx.write_shp(temp_graph, os.path.join(export_dir, 'depot.shp'))

    temp_graph = nx.DiGraph()
    for node in problem['customers']:
        temp_graph.add_node((node['latitude'],
                             node['longitude']))
    nx.write_shp(temp_graph, os.path.join(export_dir, 'customers.shp'))

    temp_graph = nx.DiGraph()
    for node in problem['stations']:
        temp_graph.add_node((node['latitude'],
                             node['longitude']))
    nx.write_shp(temp_graph, os.path.join(export_dir, 'stations.shp'))

    for ext in ('dbf', 'shp', 'shx'):
        os.remove(os.path.join(export_dir, 'edges.' + ext))

    IO.Log.info('Exported correctly to \'{}\' depot.shp, customers.shp and '
                'stations.shp\n'.format(export_dir))
    exit(0)


def get_abstract_graph(osm_graph):
    """Create a copy of the osm_graph with only necessary attributes.

        Node attributes:
            -'altitude':  elevation or height above sea level [meters]
            -'latitude':  angle with equator                  [decimal degrees]
            -'longitude': angle with greenwich                [decimal degrees]
            -'type':      'depot' or 'customer' or 'station' or ''

        Added edge attributes:
            -energy: energy spent to traverse a road          [kiloJoule]
            -rise:   altitude difference between dest and src [meters]
            -slope:  angle describing the steepness of a road [radians]
            -time:   time spent to traverse a road            [minutes]
        Kept edge attributes:
            -length:                                          [meters]
            -osm_id: open streetmap identifier of a road
            -speed:                                           [kilometers/hour]
    """
    necessary_osm_attr = ('length', 'oneway', 'osm_id')
    alt = utility.CLI.args().altitude
    ret = nx.DiGraph()

    for node, data in osm_graph.nodes_iter(data=True):
        ret.add_node(node, altitude=data[alt], type=data['type'],
                     longitude=node[0], latitude=node[1])

    for src, adjacency_dict in osm_graph.adjacency_iter():
        for dest, data in adjacency_dict.items():
            if not all(tag in data for tag in necessary_osm_attr):
                continue
            attr = dict()
            attr['length'] = data['length']
            attr['osm_id'] = data['osm_id']
            attr['rise'] = osm_graph.node[dest][alt] - osm_graph.node[src][alt]
            attr['slope'] = math.atan2(attr['rise'], attr['length'])
            if data['speed'] > 0:
                attr['speed'] = data['speed']
            elif 'maxspeed' in data and data['maxspeed'] > 0:
                attr['speed'] = data['maxspeed']
            else:
                attr['speed'] = 50  # default value if no speed available
            attr['time'] = (attr['length'] / (attr['speed'] / 3.6)) / 60.0

            def energy(rise):
                theta = -2/3 if rise < 0 else 1
                return 421200 + 1185 * 9.81 * theta * rise

            attr['energy'] = energy(attr['rise'])

            ret.add_edge(src, dest, attr_dict=attr)

            if not data['oneway']:
                attr['rise'] *= -1
                attr['energy'] = energy(attr['rise'])
                attr['slope'] *= -1
                ret.add_edge(dest, src, attr_dict=attr)

    return ret


def import_shapefile_to_workspace():
    """Populate workspace with translation of import_shapefile into a graph."""
    import_file = utility.CLI.args().import_file
    ws = utility.CLI.args().workspace

    imported_graph = nx.read_shp(path=import_file, simplify=True)
    IO.Log.info('File \'{}\' imported correctly'.format(import_file))

    if not ws:
        IO.Log.warning('Please set workspace dir')
        exit(1)

    nx.write_shp(imported_graph, ws)
    IO.Log.info('Exported correctly to \'{}\' nodes.shp and '
                'edges.shp\n'.format(ws))
    IO.Log.info('PLEASE ADD TO \'{}\' ELEVATION '
                'INFORMATION !'.format(os.path.join(ws, 'nodes.shp')))
    exit(0)


def label_nodes(graph):
    """Ensure problem is applicable to graph and label nodes of interest."""
    problem_file = utility.CLI.args().problem_file

    if not os.path.isfile(problem_file):
        IO.Log.warning('Problem file not found ({})'.format(problem_file))
        exit(1)

    with open(problem_file, 'r') as f:
        problem = yaml.load(f)

    already_labeled_nodes = list()
    depot_coor = (problem['depot']['latitude'], problem['depot']['longitude'])
    if depot_coor not in graph.nodes_iter():
        IO.Log.warning('Could not find depot {} in '
                       ' workspace'.format(depot_coor))
        exit(1)
    graph.node[depot_coor]['type'] = 'depot'
    already_labeled_nodes.append(depot_coor)

    for node in problem['customers']:
        cust_coor = (node['latitude'], node['longitude'])
        if cust_coor not in graph.nodes_iter():
            IO.Log.warning('Could not find customer {} in '
                           ' workspace'.format(cust_coor))
            exit(1)
        if cust_coor in already_labeled_nodes:
            IO.Log.warning('Could not set multiple labels to '
                           'node {} '.format(cust_coor))
            exit(1)
        graph.node[cust_coor]['type'] = 'customer'
        already_labeled_nodes.append(cust_coor)

    for node in problem['stations']:
        station_coor = (node['latitude'], node['longitude'])
        if station_coor not in graph.nodes_iter():
            IO.Log.warning('Could not find station {} in '
                           ' workspace'.format(station_coor))
            exit(1)
        if station_coor in already_labeled_nodes:
            IO.Log.warning('Could not set multiple labels to '
                           'node {} '.format(station_coor))
            exit(1)
        graph.node[station_coor]['type'] = 'station'
        already_labeled_nodes.append(station_coor)

    for node, data in graph.nodes_iter(data=True):
        if 'type' not in data:
            data['type'] = ''


def print_edge_properties(graph, fclass_whitelist=None, tag_blacklist=None):
    """For each edge matching the whitelist print tags not in the blacklist."""
    if fclass_whitelist is None:
        fclass_whitelist = ('living_street', 'motorway', 'motorway_link',
                            'primary', 'primary_link', 'residential',
                            'secondary', 'tertiary', 'unclassified')
    if tag_blacklist is None:
        tag_blacklist = ('code', 'lastchange', 'layer', 'ete', 'ShpName',
                         'Wkb', 'Wkt', 'Json')

    for node1, adjacency_dict in graph.adjacency_iter():
        for node2, data in adjacency_dict.items():
            if 'fclass' not in data or data['fclass'] in fclass_whitelist:
                print('\nLon: {}, Lat: {}  ~>'
                      '  Lon: {}, Lat: {}'.format(node1[0], node1[1],
                                                  node2[0], node2[1]))
                for tag in sorted(data):
                    if tag not in tag_blacklist:
                        print('{}: {}'.format(tag, data[tag]))


class CachePaths(object):
    """Cache of shortest and most energy-efficient routes."""

    __cache = None
    """List of tuples:
       ((src_lat, src_lon), (dst_lat, dst_lon), greenest_path, shortest_path),
       where greenest_path and shortest_path are objects of type Path.
    """

    def __add(self, graph, src, dest, greenest, shortest):
        """Append to cache two new paths between src and dest."""
        if src == dest:
            return
        record = (src, dest, Path(graph, greenest), Path(graph, shortest))
        for index, tup in enumerate(self.__cache):
            # update record if already existing
            if tup[0:2] == (src, dest):
                self.__cache[index] = record
                return
        else:
            self.__cache.append(record)

    def __init__(self, graph, type_whitelist=('depot', 'customer', 'station')):
        """Compute shortest and most efficient path."""
        self.__cache = list()

        # from each depot, customer, station ...
        for src_node, src_data in graph.nodes_iter(data=True):
            if src_data['type'] in type_whitelist:

                # get shortest paths starting from src_node
                shortest_path = nx.single_source_dijkstra_path(graph,
                                                               src_node,
                                                               weight='lenght')

                # get most energy-efficient paths from src_node
                greenest_t = nx.bellman_ford(graph, src_node, weight='energy')
                g_pred, g_energy = greenest_t

                # ... to other depot, customer, destination
                for dest_node, dest_data in graph.nodes_iter(data=True):
                    if dest_data['type'] in type_whitelist \
                       and dest_node != src_node \
                       and dest_node in shortest_path \
                       and dest_node in g_energy:
                        # unroll the path from predecessors dictionary
                        greenest_path = list()
                        node_to_add = dest_node
                        while node_to_add is not None:
                            greenest_path.append(node_to_add)
                            node_to_add = g_pred[node_to_add]
                        greenest_path = list(reversed(greenest_path))

                        self.__add(graph, src_node, dest_node,
                                   greenest_path, shortest_path[dest_node])

    def destination_iterator(self, dest):
        """Return iterator over cached records ending in dest.

           Destination is omitted from records.
        """
        return iter([(src, green, short)
                     for src, d, green, short in self.__cache if d == dest])

    def greenest(self, src, dest):
        """Return greenest Path between src and dest."""
        for source, destination, greenest, shortest in self.__cache:
            if src == source and dest == destination:
                return greenest
        raise nx.exception.NetworkxNoPath('No greenest path found between '
                                          '{} and {}'.format(src, dest))

    def shortest(self, src, dest):
        """Return shortest Path between src and dest."""
        for source, destination, greenest, shortest in self.__cache:
            if src == source and dest == destination:
                return shortest
        raise nx.exception.NetworkxNoPath('No greenest path found between '
                                          '{} and {}'.format(src, dest))

    def source_iterator(self, src):
        """Return iterator over cached records starting from src.

           Source is omitted from records.
        """
        return iter([(dest, green, short)
                     for s, dest, green, short in self.__cache if s == src])


class Path(object):
    """A path is a sequence of nodes visited in a given order."""

    __graph = None

    __nodes = None
    """List of nodes, each node is a tuple: ( latitude, longitude, type )."""

    def __init__(self, graph, coor_list=None):
        """Initialize a path from a list of node coordinates."""
        self.__graph = graph
        self.__nodes = list()
        if coor_list is None:
            return
        for lat, lon in coor_list:
            self.append(lat, lon, graph.node[(lat, lon)]['type'])

    def __iter__(self):
        """Return iterator over tuple (latitude, longitude, type)."""
        return iter(self.__nodes)

    def __repr__(self):
        return repr(self.__nodes)

    def __str__(self):
        return str(self.__nodes)

    def __sum_over_label(self, label):
        return sum([self.__graph.edge[src[:2]][self.__nodes[i + 1][:2]][label]
                    for i, src in enumerate(self.__nodes[:-1])])

    def append(self, node_latitude, node_longitude, node_type):
        """Insert node in last position of the node list."""
        self.__nodes.append((node_latitude, node_longitude, node_type))

    @property
    def energy(self):
        """Sum of the energies of each edge between the nodes in the list."""
        return self.__sum_over_label('energy')

    @property
    def length(self):
        """Sum of the lengths of each edge between the nodes in the list."""
        return self.__sum_over_label('length')

    def remove(self, node_latitude, node_longitude, node_type=''):
        """Remove from node list the specified node."""
        for index, record in enumerate(self.__nodes):
            if record[:2] == (node_latitude, node_longitude):
                del self.__nodes[index]

    def substitute(self, old_lat, old_lon, new_lat, new_lon):
        """Replace the old node with the new one."""
        for index, record in enumerate(self.__nodes):
            if record[:2] == (old_lat, old_lon):
                record = (new_lat, new_lon,
                          self.__graph.node[(new_lat, new_lon)]['type'])
                self.__nodes[index] = record

    @property
    def time(self):
        """Sum of the times of each edge between the nodes in the list."""
        return self.__sum_over_label('time')


# ----------------------------------- MAIN ---------------------------------- #

if utility.CLI.args().import_file:
    import_shapefile_to_workspace()  # <-- it always exits

if utility.CLI.args().export_dir:
    export_problem_to_directory()  # <-- it always exits

if utility.CLI.args().workspace is None:
    print('\nFirst of all import a shapefile (-i option) to a workspace '
          'directory (-w option)\n\n'
          'Then run the program specifing the workspace to use '
          '(with -w option)')
    exit(0)

check_workspace()  # <-- it exits if workspace is not compliant

osm_g = nx.read_shp(path=utility.CLI.args().workspace, simplify=True)
label_nodes(osm_g)  # <-- it exits if problem file is not applicable to graph
check_problem_solvability(osm_g)

abstract_g = get_abstract_graph(osm_g)
cache = CachePaths(abstract_g)

# Usage example
for coor, data in abstract_g.nodes_iter(data=True):
    if data['type'] == 'depot':
        # iterate over path starting from depot
        for dest, green, short in cache.source_iterator(coor):
            print(f'shortest path:  (length: {short.length}, '
                  f'energy: {short.energy}, time: {short.time})')
            for node in short:
                print('\tlat: {:2.7f}, lon: {:2.7f}, type: {}'.format(*node))

            print(f'greenest path:  (length: {green.length}, '
                  f'energy: {green.energy}, time: {green.time})')
            for node in green:
                print('\tlat: {:2.7f}, lon: {:2.7f}, type: {}'.format(*node))
            print('#' * 80)
