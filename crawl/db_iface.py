# *-* coding: utf-8 *-*

from __future__ import absolute_import

import logging

from celery import Task
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.orm import scoped_session, sessionmaker

from common.chrome_db import DB_ENGINE, extension, id_list
from common.util import MunchyMunch, dict_to_dt, PROGRESS_PERIOD
from crawl.celery import app

__all__ = ['add_new_crx_to_db', 'db_download_complete', 'db_extract_complete', 'db_profile_complete',
           'DuplicateDownload', 'SqlAlchemyTask', 'READ_ONLY']

DB_SESSION = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=DB_ENGINE))
READ_ONLY = False


class DuplicateDownload(Exception):
    """Raised when the DB already has a version of the extension."""


class SqlAlchemyTask(Task):
    """An abstract Celery Task that ensures that the connection the the
    database is closed on task completion"""
    # Some code borrowed from http://www.prschmid.com/2013/04/using-sqlalchemy-with-celery-tasks.html

    abstract = True

    def run(self, *args, **kwargs):
        """The body of the task executed by workers."""
        raise NotImplementedError('Tasks must define the run method.')

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        DB_SESSION.remove()


@app.task(base=SqlAlchemyTask)
def add_new_crx_to_db(crx_obj, log_progress=False):
    """Create entry in the table of CRX IDs.

    If the CRX is already in the list of IDs, no changes are made to the DB.

    :param crx_obj: All current information about the CRX, which must include
        at least the `id`.
    :type crx_obj: dict
    :param log_progress: Whether to log this action. Typically only set to True
        when testing, and then only for every 1K entries or so.
    :type log_progress: bool
    :rtype: None
    """
    db_session = DB_SESSION()
    log = bool(log_progress) and logging.info or logging.debug

    try:
        db_session.execute(id_list.insert().values(ext_id=crx_obj['id']))
    except IntegrityError:
        # Duplicate entry. No problem.
        log('{}  ID already in list of CRXs'.format(crx_obj['id']))
    else:
        _commit_it()
        log('{}  Added ID to list of CRXs'.format(crx_obj['id']))


@app.task(base=SqlAlchemyTask)
@MunchyMunch
def db_download_complete(crx_obj, log_progress=False):
    """Update the database with information on the downloaded extension.

    If the database already has this particular extension with a matching
    version that also has a date listed for when it was extracted and profiled,
    raise a :class:`DuplicateDownload` exception.

    :param crx_obj: All current information about the CRX, which must include
        values for `id`, `version`, `dt_avail`, and `dt_downloaded`.
    :type crx_obj: munch.Munch
    :param log_progress: Whether to log this action at DEBUG (False) or INFO
        (True) level.
    :type log_progress: bool
    :rtype: None
    """
    db_session = DB_SESSION()
    log = bool(log_progress) and logging.info or logging.debug

    # Check if the same version is already in the database
    s = select([extension.c.downloaded, extension.c.extracted, extension.c.profiled]).\
        where(and_(extension.c.ext_id == crx_obj.id, extension.c.version == crx_obj.version))
    row = db_session.execute(s).fetchone()
    if row:
        # Entry exists. First update the last known available datetime.
        u = extension.update().where(and_(extension.c.ext_id == crx_obj.id,
                                          extension.c.version == crx_obj.version)). \
            values(last_known_available=dict_to_dt(crx_obj.dt_avail))
        db_session.execute(u)
        _commit_it()
        log('{}  Updated last known available datetime after downloading'.format(crx_obj.id))

        # If the extension doesn't need any more processing, raise an error that indicates this
        if None not in list(row):
            # i.e. The extension needs to be processed if there is a value of None for the "downloaded", "extracted",
            # or "profiled" columns. If the row has no None values for these columns, we can skip it.
            raise DuplicateDownload
    else:
        # Add a new entry to the DB
        db_session.execute(extension.insert().values(ext_id=crx_obj.id,
                                                     version=crx_obj.version,
                                                     last_known_available=dict_to_dt(crx_obj.dt_avail),
                                                     downloaded=dict_to_dt(crx_obj.dt_downloaded)))
        _commit_it()
        log('{}  Added new extension entry to DB'.format(crx_obj.id))


@app.task(base=SqlAlchemyTask)
@MunchyMunch
def db_extract_complete(crx_obj, log_progress=False):
    """Update the database with information on the extracted extension.

    The two columns whose values are updated are `last_known_available` and
    `extracted`.

    :param crx_obj: All current information about the CRX, which must include
        values for `id`, `version`, `dt_avail`, and `dt_extracted`.
    :type crx_obj: munch.Munch
    :param log_progress: Whether to log this action at DEBUG (False) or INFO
        (True) level.
    :type log_progress: bool
    :rtype: None
    """
    db_session = DB_SESSION()
    log = bool(log_progress) and logging.info or logging.debug

    u = extension.update().where(and_(extension.c.ext_id == crx_obj.id,
                                      extension.c.version == crx_obj.version)). \
        values(last_known_available=dict_to_dt(crx_obj.dt_avail),
               extracted=dict_to_dt(crx_obj.dt_extracted))
    db_session.execute(u)
    _commit_it()
    log('{}  Updated DB after extracting extension'.format(crx_obj.id))


@app.task(base=SqlAlchemyTask)
@MunchyMunch
def db_profile_complete(crx_obj, log_progress=False, update_dt_avail=True):
    """Update DB that profiling is now complete, including centroid data.

    The value of `update_dt_avail` should only be set to False when
    re-profiling the extensions in the database. Currently, the only known
    reason for re-profiling is the development of a new formula for calculating
    centroids. In this case, the `last_known_available` column in the database
    should NOT be updated.

    Adds the following keys to `crx_obj.cent_dict`:

    - `ext_id`: Corresponds to `crx_obj.id`.
    - `version`:  Corresponds to `crx_obj.version`.
    - `last_known_available`:  Corresponds to `crx_obj.dt_avail`. (Only added
      if the `update_dt_avail` parameter is True.)
    - `profiled`:  Corresponds to `crx_obj.dt_profiled`.

    :param crx_obj: Previously collected information about the extension.
    :type crx_obj: munch.Munch
    :param log_progress: Whether to log this action at DEBUG (False) or INFO
        (True) level.
    :type log_progress: bool
    :param update_dt_avail: If re-profiling, this should be set to True.
    :type update_dt_avail: bool
    :return: Updated version of `crx_obj`.
    :rtype: munch.Munch
    """
    db_session = DB_SESSION()
    log = bool(log_progress) and logging.info or logging.debug

    # Store values for update in cent_dict
    crx_obj.cent_dict['ext_id'] = crx_obj.id
    crx_obj.cent_dict['version'] = crx_obj.version
    crx_obj.cent_dict['profiled'] = dict_to_dt(crx_obj.dt_profiled)
    if update_dt_avail:
        crx_obj.cent_dict['last_known_available'] = dict_to_dt(crx_obj.dt_avail)

    # Update the DB with values from cent_dict
    u = extension.update().where(and_(extension.c.ext_id == crx_obj.id, extension.c.version == crx_obj.version)).\
        values(crx_obj.cent_dict)
    db_session.execute(u)
    _commit_it()

    # Create a stats message indicating what happened
    if update_dt_avail:
        crx_obj.msgs.append('+Successfully updated profile info for an extension entry in the DB')
    else:
        crx_obj.msgs.append('*Re-profiled an extension and updated its entry in the DB')

    log('{}  Database entry complete (profile)'.format(crx_obj.id))

    return crx_obj


def _commit_it():
    """Commit pending transactions if not running in READ_ONLY mode."""
    db_session = DB_SESSION()
    try:
        if READ_ONLY:
            db_session.rollback()
        else:
            db_session.commit()
    except InvalidRequestError:
        # Indicates there were no pending transactions to commit/rollback. Just ignore.
        pass
