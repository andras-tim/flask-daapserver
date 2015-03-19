from datetime import datetime

import cStringIO

__all__ = ("LocalFileProvider", "Provider", "Session")


class DummyLock(object):
    """
    Dummy lock implementation.
    """

    __slots__ = ()

    def __enter__(self):
        pass

    def __exit__(self, typ, value, traceback):
        pass


class Session(object):
    """
    Represents a client session.
    """

    __slots__ = ("revision", "since", "user_agent", "state")

    def __init__(self):
        self.revision = 0
        self.user_agent = None
        self.since = datetime.now()
        self.state = State.connected


class Provider(object):
    """
    Base provider implementation. A provider is responsible for serving the
    data to the client. This class should be subclassed.
    """

    # Class type to use for sessions
    session_class = Session

    # Whether to artwork is supported
    supports_artwork = False

    # Whether persistent IDs are supported
    supports_persistent_id = False

    def __init__(self):
        """
        Create a new Provider.

        Note: `self.server' should be declared. If using a threaded server,
        make sure `self.lock` is an applicable lock.
        """

        self.server = None
        self.sessions = {}
        self.session_counter = 0
        self.lock = DummyLock()

    def create_session(self):
        """
        Create a new session.

        :return: The new session id
        :rtype: int
        """

        self.session_counter += 1
        self.sessions[self.session_counter] = self.session_class()

        return self.session_counter

    def destroy_session(self, session_id):
        """
        Destroy an (existing) session.
        """

        try:
            del self.sessions[session_id]
        except KeyError:
            pass

    def get_revision(self, session_id, revision, delta):
        """
        Determine the next revision number for a given session id, revision
        and delta.

        In case the client is up-to-date, this method will block via
        `self.wait_for_update` until the next revision is available.

        :param int session_id: Session identifier
        :param int revision: Client revision number
        :param int delta: Client revision delta (old client version number)
        :return: Next revision number
        :rtype: int
        """

        session = self.sessions[session_id]

        if delta == revision:
            # Increment revision. Never decrement.
            session.revision = max(session.revision, revision)

            # Check sessions.
            self.check_sessions()

            # Wait for next revision
            next_revision = self.wait_for_update()
        else:
            next_revision = self.server.storage.revision

        return next_revision

    def check_sessions(self):
        """
        Check if the revision history can be cleaned. This is the case when
        all connected clients have the same revision as the server has.
        """

        lowest_revision = min(
            session.revision for session in self.sessions.itervalues())

        # Remove all old revision history
        if lowest_revision == self.server.storage.revision:
            with self.lock:
                self.server.storage.clean(lowest_revision)

    def wait_for_update(self):
        """
        Wait for the next revision to become available. This method should
        block and return the next revision number.

        :return: Next revision number
        :rtype: int
        """

        raise NotImplemented("Needs to be overridden")

    def get_databases(self, session_id, revision, delta):
        """
        """

        if delta == 0:
            new = self.server.databases
            old = None
        else:
            new = self.server.databases(revision)
            old = self.server.databases(delta)

        return new, old

    def get_containers(self, session_id, database_id, revision, delta):
        """
        """

        if delta == 0:
            new = self.server \
                      .databases[database_id] \
                      .containers
            old = None
        else:
            new = self.server \
                      .databases(revision)[database_id] \
                      .containers(revision)
            old = self.server \
                      .databases(delta)[database_id] \
                      .containers(delta)

        return new, old

    def get_container_items(self, session_id, database_id, container_id,
                            revision, delta):
        """
        """

        if delta == 0:
            new = self.server \
                      .databases[database_id] \
                      .containers[container_id] \
                      .container_items
            old = None
        else:
            new = self.server \
                      .databases(revision)[database_id] \
                      .containers(revision)[container_id] \
                      .container_items(revision)
            old = self.server \
                      .databases(delta)[database_id] \
                      .containers(delta)[container_id] \
                      .container_items(delta)

        return new, old

    def get_items(self, session_id, database_id, revision, delta):
        """
        """

        if delta == 0:
            new = self.server \
                      .databases[database_id] \
                      .items
            old = None
        else:
            new = self.server \
                      .databases(revision)[database_id] \
                      .items(revision)
            old = self.server \
                      .databases(delta)[database_id] \
                      .items(delta)

        return new, old

    def get_item(self, session_id, database_id, item_id, byte_range=None):
        """
        """

        session = self.sessions[session_id]
        item = self.server.databases[database_id].items[item_id]

        return self.get_item_data(session, item, byte_range)

    def get_artwork(self, session_id, database_id, item_id):
        """
        """

        session = self.sessions[session_id]
        item = self.server.databases[database_id].items[item_id]

        return self.get_artwork_data(session, item)

    def get_item_data(self, session, item, byte_range=None):
        """
        Fetch the requested item. The result can be an iterator, file
        descriptor, or just raw bytes. Optionally, a begin and/or end range can
        be specified.

        The result should be an tuple, of the form (data, mimetype, size). The
        data can be an iterator, file descriptor or raw bytes. In case a range
        is requested, add a fourth tuple item, length. The length should be the
        size of the requested data that is being returned.

        Note: this method requires `Provider.supports_artwork = True'
        """

        raise NotImplemented("Needs to be overridden")

    def get_artwork_data(self, session, item):
        """
        Fetch artwork for the requested item.

        The result should be an tuple, of the form (data, mimetype, size). The
        data can be an iterator, file descriptor or raw bytes.

        Note: this method requires `Provider.supports_artwork = True'
        """

        raise NotImplemented("Needs to be overridden")


class LocalFileProvider(Provider):

    supports_artwork = True

    def get_item(self, session, item, byte_range=None):
        begin, end = byte_range if byte_range else 0, item.file_size
        fp = open(item.file_path, "rb+")

        if not begin:
            return fp, item.mimetype, item.file_size
        elif begin and not end:
            fp.seek(begin)
            return fp, item.mimetype, item.file_size
        elif begin and end:
            fp.seek(begin)

            data = fp.read(end - begin)
            result = cStringIO.StringIO(data)

            return result, item.mimetype, item.file_size

    def get_artwork_data(self, session, item):
        fp = open(item.artwork, "rb+")

        return fp, None, None
