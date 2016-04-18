# Copyright 2016 Splunk, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"): you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

'''
This module provides a base class of Splunk modular input.
'''

import sys
import urllib2
import logging
import traceback
import urlparse
from abc import ABCMeta, abstractmethod
try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET

from splunklib import binding
from splunklib.modularinput.argument import Argument
from splunklib.modularinput.scheme import Scheme
from splunklib.modularinput.input_definition import InputDefinition
from splunklib.modularinput.validation_definition import ValidationDefinition

from solnlib import utils
from solnlib.modular_input import checkpointer
from solnlib.modular_input import event_writer
from solnlib.orphan_process_monitor import OrphanProcessMonitor

__all__ = ['ModularInput']


class ModularInput(object):
    '''Base class of Splunk modular input.

    It's a base modular input, it should be inherited by sub modular
    input. For sub modular input, some class properties must be overriden,
    like: app, name, title and description, also there are some other
    optional properties can be overriden like: use_external_validation,
    use_single_instance, use_kvstore_checkpoint, use_hec_event_writer etc..

    Usage::

       >>> Class TestModularInput(ModularInput):
       >>>     app = 'TestApp'
       >>>     name = 'TestModularInput'
       >>>     title = 'Test modular input'
       >>>     description = 'This is a test modular input'
       >>>
       >>>     def extra_arguments(self):
       >>>         ... .. .
       >>>
       >>>     def do_validation(self, parameters):
       >>>         ... .. .
       >>>
       >>>     def do_run(self, inputs):
       >>>         ... .. .
       >>>
       >>> if __name__ == '__main__':
       >>>     md = TestModularInput()
       >>>     md.execute()
    '''

    __metaclass__ = ABCMeta

    # App name, must be overriden
    app = None
    # Modular input name, must be overriden
    name = None
    # Modular input scheme title, must be overriden
    title = None
    # Modular input scheme description, must be overriden
    description = None
    # Modular input scheme use external validation, default is False
    use_external_validation = False
    # Modular input scheme use single instance mode, default is False
    use_single_instance = False
    # Use kvstore for checkpoint, default is True
    use_kvstore_checkpoint = True
    # Collection name of kvstore checkpoint, default is 'kvstore_checkpoint'
    kvstore_checkpoint_collection_name = 'solnlib_kvstore_checkpoint'
    # Use hec event writer
    use_hec_event_writer = True
    # Input name of Splunk HEC. Must override if use HEC to do data injection
    hec_input_name = ''

    def __init__(self):
        # Metadata
        self._server_host_name = None
        self._server_uri = None
        self._server_scheme = None
        self._server_host = None
        self._server_port = None
        self._session_key = None
        self._checkpoint_dir = None
        # Checkpoint
        self._checkpointer = None
        # Orphan process monitor
        self._orphan_monitor = None
        # Event writer
        self._event_writer = None

    def _update_metadata(self, metadata):
        self._server_host_name = metadata['server_host']
        splunkd = urllib2.urlparse.urlsplit(metadata['server_uri'])
        self._server_uri = splunkd.geturl()
        self._server_scheme = splunkd.scheme
        self._server_host = splunkd.hostname
        self._server_port = splunkd.port
        self._session_key = metadata['session_key']
        self._checkpoint_dir = metadata['checkpoint_dir']

    @property
    def server_host_name(self):
        '''Get splunk server host name.

        :returns: splunk server host name.
        :rtype: ``string``
        '''

        return self._server_host_name

    @property
    def server_uri(self):
        '''Get splunk server uri.

        :returns: splunk server uri.
        :rtype: ``string``
        '''

        return self._server_uri

    @property
    def server_scheme(self):
        '''Get splunk server scheme.

        :returns: splunk server scheme.
        :rtype: ``string``
        '''

        return self._server_scheme

    @property
    def server_host(self):
        '''Get splunk server host.

        :returns: splunk server host.
        :rtype: ``string``
        '''

        return self._server_host

    @property
    def server_port(self):
        '''Get splunk server port.

        :returns: splunk server port.
        :rtype: ``integer``
        '''

        return self._server_port

    @property
    def session_key(self):
        '''Get splunkd session key.

        :returns: splunkd session key.
        :rtype: ``string``
        '''

        return self._session_key

    @property
    def checkpointer(self):
        '''Get checkpointer instance.

        The checkpointer returned depends on use_kvstore_checkpoint flag,
        if use_kvstore_checkpoint is true will return an KVStoreCheckpoint
        instance else an FileCheckpoint instance.

        :returns: An checkpointer instance.
        :rtype: ``Checkpointer object``
        '''

        if self._checkpointer is None:
            if self.use_kvstore_checkpoint:
                splunkd = urlparse.urlparse(self._server_uri)
                self._checkpointer = checkpointer.KVStoreCheckpointer(
                    self.kvstore_checkpoint_collection_name, self._session_key,
                    self.app, owner='nobody', scheme=splunkd.scheme,
                    host=splunkd.hostname, port=splunkd.port)
            else:
                self._checkpointer = checkpointer.FileCheckpointer(
                    self._checkpoint_dir)

        return self._checkpointer

    @property
    def event_writer(self):
        '''Get event writer instance.

        The event writer returned depends on use_hec_event_writer flag,
        if use_hec_event_writer is true will return an HECEventWriter
        instance else an ClassicEventWriter instance.

        :returns: Event writer instance.
        :rtype: ``EventWriter object``
        '''

        if self._event_writer:
            return self._event_writer

        if self.use_hec_event_writer:
            assert self.hec_input_name, "hec_input_name is not set"
            try:
                self._event_writer = event_writer.HECEventWriter(
                    self.hec_input_name, self._session_key,
                    scheme=self.server_scheme, host=self.server_host,
                    port=self.server_port)
            except binding.HTTPError:
                logging.error(
                    'Failed to init HECEventWriter, will use '
                    'ClassicEventWriter instead.')
                self._event_writer = event_writer.ClassicEventWriter()
        else:
            self._event_writer = event_writer.ClassicEventWriter()

        return self._event_writer

    def _do_scheme(self):
        scheme = Scheme(self.title)
        scheme.description = self.description
        scheme.use_external_validation = self.use_external_validation
        scheme.streaming_mode = Scheme.streaming_mode_xml
        scheme.use_single_instance = self.use_external_validation

        for argument in self.extra_arguments():
            name = argument['name']
            title = argument.get('title', None)
            description = argument.get('description', None)
            validation = argument.get('validation', None)
            data_type = argument.get('data_type', Argument.data_type_string)
            required_on_edit = argument.get('required_on_edit', False)
            required_on_create = argument.get('required_on_create', False)

            scheme.add_argument(
                Argument(name, title=title, description=description,
                         validation=validation, data_type=data_type,
                         required_on_edit=required_on_edit,
                         required_on_create=required_on_create))

        return ET.tostring(scheme.to_xml())

    def extra_arguments(self):
        '''Extra arguments for modular input.

        Default implementation is returning an empty list.

        :returns: List of arguments like: [{'name': 'arg1',
                                            'title': 'arg1 title',
                                            'description': 'arg1 description',
                                            'validation': 'arg1 validation statement',
                                            'data_type': Argument.data_type_string,
                                            'required_on_edit': False,
                                            'required_on_create': False},
                                            {...},
                                            {...}]
        :rtype: ``list``
        '''

        return []

    def do_validation(self, parameters):
        '''Handles external validation for modular input kinds.

        When Splunk calls a modular input script in validation mode, it will
        pass in an XML document giving information about the Splunk instance
        (so you can call back into it if needed) and the name and parameters
        of the proposed input. If this function does not throw an exception,
        the validation is assumed to succeed. Otherwise any errors thrown will
        be turned into a string and logged back to Splunk.

        :param parameters: The parameters of input passed by splunkd.

        :raises Exception: If validation is failed.
        '''

        pass

    def _do_run(self, inputs):
        self.do_run(inputs)

    @abstractmethod
    def do_run(self, inputs):
        '''Runs this modular input

        :param inputs: Dict of command line arguments passed to this script,
           like: {'stanza_name': {'arg1': 'arg1_value', 'arg2': 'arg2_value', ...}}.
        :type inputs: ``dict``
        '''

        pass

    def register_teardown_handler(self, handler, *args):
        '''Register teardown signal handler.

        :param handler: Teardown signal handler.

        Usage::
           >>> mi = ModularInput(...)
           >>> def teardown_handler(arg1, arg2, ...):
           >>>     ...
           >>> mi.register_teardown_handler(teardown_handler, arg1, arg2, ...)
        '''

        def _teardown_handler(signum, frame):
            handler(*args)

        utils.handle_teardown_signals(_teardown_handler)

    def register_orphan_handler(self, handler, *args):
        '''Register orphan process handler.

        :param handler: Orphan process handler.

        Usage::
           >>> mi = ModularInput(...)
           >>> def orphan_handler(arg1, arg2, ...):
           >>>     ...
           >>> mi.register_orphan_handler(orphan_handler, arg1, arg2, ...)
        '''

        def _orphan_handler():
            handler(*args)

        if self._orphan_monitor is None:
            self._orphan_monitor = OrphanProcessMonitor(_orphan_handler)
            self._orphan_monitor.start()

    def execute(self):
        '''Modular input entry.

        Usage::
           >>> Class TestModularInput(ModularInput):
           >>>         ... .. .
           >>>
           >>> if __name__ == '__main__':
           >>>     md = TestModularInput()
           >>>     md.execute()
        '''

        if len(sys.argv) == 1:
            try:
                input_definition = InputDefinition.parse(sys.stdin)
                self._update_metadata(input_definition.metadata)
                self._do_run(input_definition.inputs)
                logging.info('Modular input: %s exit normally.', self.title)
                return 0
            except Exception as e:
                logging.error('Modular input: %s exit with exception: %s.',
                              self.name, traceback.format_exc(e))
                return 1
            finally:
                # Stop event writer if any
                if self._event_writer:
                    self._event_writer.close()
                # Stop orphan monitor if any
                if self._orphan_monitor:
                    self._orphan_monitor.stop()

        elif str(sys.argv[1]).lower() == '--scheme':
            sys.stdout.write(self._do_scheme())
            sys.stdout.flush()
            return 0

        elif sys.argv[1].lower() == '--validate-arguments':
            try:
                validation_definition = ValidationDefinition.parse(sys.stdin)
                self._update_metadata(validation_definition.metadata)
                self.do_validation(validation_definition.parameters)
                return 0
            except Exception as e:
                logging.error(
                    'Modular input: %s validate arguments with exception: %s.',
                    self.name, traceback.format_exc(e))
                root = ET.Element('error')
                ET.SubElement(root, 'message').text = str(e)
                sys.stderr.write(ET.tostring(root))
                sys.stderr.flush()
                return 1
        else:
            logging.error(
                'Modular input: %s run with invalid arguments: "%s".',
                self.name, ' '.join(sys.argv[1:]))
            return 1
