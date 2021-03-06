from datetime import datetime
import json
from re import match
from subprocess import check_output

from bs4 import BeautifulSoup as Bsoup
from plotly import offline as plotoff
from plotly.graph_objs import Bar, Layout, Figure
from sqlalchemy import Table, select, update, and_, insert, desc

from common.chrome_db import *

TESTING = False


def set_all_centroid_families():
    # Look through the DB for extension entries that don't have a centroid family listed
    db_conn = DB_META.bind.connect()  # Connect to the database

    # Get a handle on the two tables
    extension = Table('extension', DB_META)
    cent_fam = Table('centroid_family', DB_META)

    # Cycle through all the entries that don't have an assigned centroid family yet
    s = select([extension]).where(extension.c.centroid_group.is_(None))
    cnt = 0
    for e_row in db_conn.execute(s):
        s_fam = select([cent_fam]).where(and_(cent_fam.c.size == e_row[extension.c.size],
                                              # cent_fam.c.ctime == e_row[extension.c.ctime],
                                              cent_fam.c.num_dirs == e_row[extension.c.num_dirs],
                                              cent_fam.c.num_files == e_row[extension.c.num_files],
                                              cent_fam.c.ttl_files == e_row[extension.c.ttl_files],
                                              cent_fam.c.perms == e_row[extension.c.perms],
                                              cent_fam.c.depth == e_row[extension.c.depth],
                                              cent_fam.c.type == e_row[extension.c.type],))

        f_row = db_conn.execute(s_fam).fetchone()
        if f_row:
            with db_conn.begin():
                # Entry exists. Add the index to the extension row to connect to the family
                db_conn.execute(update(extension).where(extension.c.pk == e_row['pk']).
                                values(centroid_group=f_row['pk']))

                # Increment the membership count and set the last updated value to now
                db_conn.execute(update(cent_fam).where(cent_fam.c.pk == f_row['pk']).
                                values(num_members=f_row['num_members']+1,
                                       members_updated=datetime.today()))
            cnt += 1

        else:
            with db_conn.begin():
                # Family entry doesn't exist, create it with a family membership count of 1, last updated value of now
                fam_vals = {'size': e_row[extension.c.size],
                            # 'ctime': e_row[extension.c.ctime],
                            'num_dirs': e_row[extension.c.num_dirs],
                            'num_files': e_row[extension.c.num_files],
                            'ttl_files': e_row[extension.c.ttl_files],
                            'perms': e_row[extension.c.perms],
                            'depth': e_row[extension.c.depth],
                            'type': e_row[extension.c.type],
                            'num_members': 1,
                            'members_updated': datetime.today()}
                res = db_conn.execute(insert(cent_fam).values(fam_vals))

                # Add the index of the new family to the extension row to connect them
                db_conn.execute(update(extension).where(extension.c.pk == e_row['pk']).
                                values(centroid_group=res.inserted_primary_key[0]))
            cnt += 1

        if cnt and not cnt % 1000:
            print('Added %d extensions to a family' % cnt)

    print('Added %d extensions to a family' % cnt)

    # TODO: We should do the same kind of thing for all the extensions' i_centroid_group

    calc_it(db_conn)

    db_conn.close()


def calc_it(db_conn=None):
    close_conn = False
    if db_conn is None:
        close_conn = True
        db_conn = DB_META.bind.connect()  # Connect to the database

    # Get a handle on the two tables
    extension = Table('extension', DB_META)
    cent_fam = Table('centroid_family', DB_META)

    # Cycle through the centroid family IDs
    # TODO: Make this more efficient by selecting only those that are NULL or all members > distinct
    s = select([cent_fam.c.pk])
    for f2_row in db_conn.execute(s):
        # Query the extension table for the members of the family, counting the distinct ones
        all_mem = select([extension.c.ext_id, extension.c.pk]).\
            where(extension.c.centroid_group == f2_row[cent_fam.c.pk]).alias('all_members')
        s_cnt = select([all_mem.c.ext_id], distinct=True).select_from(all_mem).alias('distinct_id_members').count()
        # print(str(s_cnt))
        # break
        n = int(db_conn.execute(s_cnt).fetchone()[0])

        # Add this count as the distinct_id_members field
        with db_conn.begin():
            db_conn.execute(update(cent_fam).where(cent_fam.c.pk == f2_row[cent_fam.c.pk]).
                            values(distinct_id_members=n,
                                   distinct_members_updated=datetime.today()))

    if close_conn:
        db_conn.close()


def reset_membership_counts():
    # Have the DB tell us how many extensions are part of each family
    pass


def count_ext_versions():
    db_conn = DB_META.bind.connect()  # Connect to the database

    # Get a handle on the table
    extension = Table('extension', DB_META)

    # Get the list of distinct CRX IDs from the extension table
    # We don't want to get the list from the id_list table because not all the IDs in that table are helpful here
    s = select([extension.c.ext_id]).distinct()
    version_counts = {}
    id_cnt = 0

    # For each distinct ID, count how many rows have that ID
    for d_row in db_conn.execute(s):
        s_cnt = select([extension.c.version]).where(extension.c.ext_id == d_row[extension.c.ext_id]).\
            alias('version_count').count()
        n = db_conn.execute(s_cnt).fetchone()[0]

        try:
            version_counts[n] += 1
        except KeyError:
            version_counts[n] = 1

        id_cnt += 1
        if not id_cnt % 1000:
            print('Counted versions of %d IDs' % id_cnt)

    db_conn.close()

    # Make a backup of the data
    with open('version_counts.json', 'w') as fout:
        json.dump(version_counts, fout)

    # Plot the data
    plot_data(version_counts)


def plot_from_count_backup():
    with open('version_counts.json') as fin:
        counts = json.load(fin)
    plot_data(counts)


def plot_data(counts):
    """
    Create a plot of the data in the counts dict.

    :param counts: Dictionary of {version_count: ID_count}.
    :type counts: dict
    :return: None
    :rtype: None
    """
    # Create the plot of the data
    d = {'x': [], 'y': []}
    for x in counts:
        d['x'].append(x)
        d['y'].append(counts[x])
    data = [Bar(x=d['x'], y=d['y'])]

    plotoff.plot(data, show_link=False, filename='count_ext_versions_graph.html', auto_open=False)


def get_top_exts(web_store_scrape_file, with_num_ratings=False):
    """
    Scrape the file, return the extension IDs.

    :param web_store_scrape_file: Should be a path to a HTML file taken from
        the Chrome Web Store showing the "Popular" category. There's no
        guarantee that the CSS and tag attributes used to locate the desired
        information will work in the future. Check the Web Store's source to be
        sure.
    :type web_store_scrape_file: str
    :param with_num_ratings: Flag indicates if the number of reviews should
        also be returned. If True, the return type will be a dictionary.
    :type with_num_ratings: bool
    :return: The list of extension IDs.
    :rtype: tuple|dict
    """
    soup = Bsoup(web_store_scrape_file, "lxml")
    ext_num_ratings = {}

    for tile in soup.find_all('div', class_='webstore-test-wall-tile'):
        link = tile.a.get('href')
        ext_id = id_from_url(link)

        rating = tile.find('div', attrs={'g:type': "AverageStarRating"})
        num_ratings = int(rating.span.string[1:-1])  # Number with parentheses around them

        ext_num_ratings[ext_id] = num_ratings

    if with_num_ratings:
        return ext_num_ratings
    return tuple(ext_num_ratings.keys())


def id_from_url(url):
    """
    Extract the extension ID from a Web Store URL.

    :param url: URL to the extension on the Chrome Web Store.
    :type url: str
    :return: The 32-character ID, or None.
    :rtype: str|None
    """
    pat = r'https://chrome.google.com/webstore/detail.*/([a-z]{32})/?'
    m = match(pat, url)
    if m:
        return m.group(1)


def get_num_files():
    # Get a handle on the DB and table
    db_conn = DB_META.bind.connect()
    extension = Table('extension', DB_META)

    # Iterate through the DB, get the ID and version number
    s = select([extension.c.pk, extension.c.ext_id, extension.c.version]).where(extension.c.ttl_files.is_(None))
    cnt = 0
    not_found = 0
    for row in db_conn.execute(s):
        # CWD to the location of the unpacked CRX
        the_dir = '/var/lib/dbling/unpacked/{}/{}'.format(row[extension.c.ext_id], row[extension.c.version])

        # Execute `find | wc -l` to get the number of files
        try:
            ttl_files = int(check_output('/usr/bin/find | /usr/bin/wc -l', shell=True, cwd=the_dir).strip())
        except FileNotFoundError:
            # Doesn't hurt anything that we don't have the files for this extension, but we should count it
            not_found += 1
            continue

        # Update the DB with the number of files
        with db_conn.begin():
            db_conn.execute(update(extension).where(extension.c.pk == row[extension.c.pk]).values(ttl_files=ttl_files))

        cnt += 1
        if cnt and not cnt % 1000:
            print('Counted files for %d extensions' % cnt)

    print('Counted files for %d extensions' % cnt)
    if not_found:
        print("%d database entries don't have corresponding files saved." % not_found)
    db_conn.close()


def family_histogram():
    db_conn = DB_META.bind.connect()
    cent_fam = Table('centroid_family', DB_META)

    # Get the number of members in each centroid family, in descending order
    d = {'x': [], 'y': []}
    s = select([cent_fam.c.distinct_id_members]).order_by(desc(cent_fam.c.distinct_id_members))
    x = 0

    for row in db_conn.execute(s):
        x += 1
        d['x'].append(x)
        d['y'].append(row[cent_fam.c.distinct_id_members])
        if x >= 200:
            break
    db_conn.close()

    data = [Bar(x=d['x'], y=d['y'])]
    layout = Layout(xaxis=dict(autorange=True), yaxis=dict(type='log', autorange=True))
    fig = Figure(data=data, layout=layout)

    plotoff.plot(fig, show_link=False, filename='centroid_family_hist.html')#, auto_open=False, layout=layout)


def tao_histo():
    db_conn = DB_META.bind.connect()
    extension = Table('extension', DB_META)

    d = {'x': [], 'y': []}

    # Get the set of distinct ttl_files values
    s = select([extension.c.ttl_files], distinct=True)

    for dist in db_conn.execute(s):
        x = dist[extension.c.ttl_files]
        t_cnt = select([extension.c.pk]).where(extension.c.ttl_files == x).alias('tao').count()
        y = db_conn.execute(t_cnt).fetchone()[0]
        d['x'].append(x)
        d['y'].append(y)

    data = [Bar(x=d['x'], y=d['y'])]
    plotoff.plot(data, show_link=False, filename='tao_histo.html', auto_open=True)
