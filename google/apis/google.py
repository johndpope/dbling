# -*- coding: utf-8 -*-

from apiclient import discovery
from httplib2 import Http
from maya import parse, when, get_localzone
from pytz import all_timezones

from util import set_http


class GoogleAPI:
    """Interface to the Google API.

    See the documentation for subclasses for more detailed information.
    """

    _service_name = NotImplemented
    _version = NotImplemented

    def __init__(self, http=None, impersonated_user_email=None, start=None, end=None, timezone=None):
        """
        :param httplib2.Http http: An Http object for sending the requests. In
            general, this should be left as None, which will allow for
            auto-adjustment of the kind of Http object to create based on
            whether a user's email address is to be impersonated.
        :param str impersonated_user_email: The email address of a user to
            impersonate. This requires domain-wide delegation to be activated.
            See
            https://developers.google.com/admin-sdk/reports/v1/guides/delegation
            for instructions.
        :param str start: The earliest data to collect. Can be any kind of date
            string, as long as it is unambiguous (e.g. "2017"). It can even be
            slang, such as "a year ago". Be aware, however, that only the *day*
            of the date will be used, meaning *time* information will be
            discarded.
        :param str end: The latest data to collect. Same format rules apply for
            this as for the ``start`` parameter.
        :param str timezone: The timezone to convert all timestamps to before
            compiling. This should be a standard timezone name. For reference,
            the list that the timezone will be compared against is available at
            https://github.com/newvem/pytz/blob/master/pytz/__init__.py. If
            omitted, the local timezone of the computer will be used.
        """
        if NotImplemented in (self._service_name, self._version):
            raise ValueError('Implementing classes of GoogleAPI must set a value for _service_name and _version.')

        self.email = impersonated_user_email

        # By default, set the timezone to whatever the local timezone is. Otherwise set it to what the user specified.
        if timezone is None or timezone not in all_timezones:
            self.tz = str(get_localzone())
        else:
            self.tz = timezone

        # Interpret the start and end times
        if start is None:
            self.start = start
        else:
            try:
                self.start = parse(start).datetime().date()  # First, assume they gave a well-formatted time
            except ValueError:
                self.start = when(start).datetime().date()  # Next, attempt to interpret the time as slang

        if end is None:
            self.end = end
        else:
            try:
                self.end = parse(end).datetime().date()
            except ValueError:
                self.end = when(end).datetime().date()

        self.customer_id = 'my_customer'  # Only used by directory API

        # The following are accessed by their respective class properties
        self._http = http
        self._service = None
        self._team_drives = None

    @property
    def http(self):
        if self._http is None or not isinstance(self._http, Http):
            self._http = set_http(impersonated_user_email=self.email)
        return self._http

    @property
    def service(self):
        # Create the service object, which provides a connection to Google
        if self._service is None:
            self._service = discovery.build(serviceName=self._service_name, version=self._version, http=self.http)
        return self._service

    def get_all(self):
        raise NotImplementedError
        # TODO: Finish intelligent get_all
        r = {}
        for m in [x for x in dir(self) if x.startswith('get_')]:
            r[m[4:]] = getattr(self, m)()
        return r
