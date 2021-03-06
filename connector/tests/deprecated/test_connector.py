# -*- coding: utf-8 -*-
# Copyright 2013-2017 Camptocamp SA
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html)

import mock
import unittest

from odoo import api
from odoo.modules.registry import RegistryManager
from odoo.tests import common
from odoo.addons.connector import connector
from odoo.addons.queue_job.exception import RetryableJobError
from odoo.addons.connector.connector import (
    is_module_installed,
    get_odoo_module,
    ConnectorEnvironment,
    ConnectorUnit,
)


def mock_connector_unit(env):
    backend_record = mock.Mock(name='BackendRecord')
    backend_record.env = env
    backend = mock.Mock(name='Backend')
    backend_record.get_backend.return_value = backend
    connector_env = connector.ConnectorEnvironment(backend_record,
                                                   'res.users')
    return ConnectorUnit(connector_env)


class TestModuleInstalledFunctions(common.TransactionCase):

    def test_is_module_installed(self):
        """ Test on an installed module """
        self.assertTrue(is_module_installed(self.env, 'connector'))

    def test_is_module_uninstalled(self):
        """ Test on an installed module """
        self.assertFalse(is_module_installed(self.env, 'lambda'))

    def test_get_odoo_module(self):
        """ Odoo module is found from a Python path """
        self.assertEquals(get_odoo_module(TestModuleInstalledFunctions),
                          'connector')


class TestConnectorUnit(unittest.TestCase):
    """ Test Connector Unit """

    def test_connector_unit_for_model_names(self):
        model = 'res.users'

        class ModelUnit(ConnectorUnit):
            _model_name = model

        self.assertEqual(ModelUnit.for_model_names, [model])

    def test_connector_unit_for_model_names_several(self):
        models = ['res.users', 'res.partner']

        class ModelUnit(ConnectorUnit):
            _model_name = models

        self.assertEqual(ModelUnit.for_model_names, models)

    def test_connector_unit_no_model_name(self):
        with self.assertRaises(NotImplementedError):
            ConnectorUnit.for_model_names  # pylint: disable=W0104

    def test_match(self):

        class ModelUnit(ConnectorUnit):
            _model_name = 'res.users'

        env = mock.Mock(name='Environment')

        self.assertTrue(ModelUnit.match(env, 'res.users'))
        self.assertFalse(ModelUnit.match(env, 'res.partner'))

    def test_unit_for(self):

        class ModelUnit(ConnectorUnit):
            _model_name = 'res.users'

        class ModelBinder(ConnectorUnit):
            _model_name = 'res.users'

        backend_record = mock.Mock(name='BackendRecord')
        backend = mock.Mock(name='Backend')
        backend_record.get_backend.return_value = backend
        backend_record.env = mock.MagicMock(name='Environment')
        # backend.get_class() is tested in test_backend.py
        backend.get_class.return_value = ModelUnit
        connector_env = connector.ConnectorEnvironment(backend_record,
                                                       'res.users')
        unit = ConnectorUnit(connector_env)
        # returns an instance of ModelUnit with the same connector_env
        new_unit = unit.unit_for(ModelUnit)
        self.assertEqual(type(new_unit), ModelUnit)
        self.assertEqual(new_unit.connector_env, connector_env)

        backend.get_class.return_value = ModelBinder
        # returns an instance of ModelBinder with the same connector_env
        new_unit = unit.binder_for()
        self.assertEqual(type(new_unit), ModelBinder)
        self.assertEqual(new_unit.connector_env, connector_env)

    def test_unit_for_other_model(self):

        class ModelUnit(ConnectorUnit):
            _model_name = 'res.partner'

        class ModelBinder(ConnectorUnit):
            _model_name = 'res.partner'

        backend_record = mock.Mock(name='BackendRecord')
        backend = mock.Mock(name='Backend')
        backend_record.get_backend.return_value = backend
        backend_record.env = mock.MagicMock(name='Environment')
        # backend.get_class() is tested in test_backend.py
        backend.get_class.return_value = ModelUnit
        connector_env = connector.ConnectorEnvironment(backend_record,
                                                       'res.users')
        unit = ConnectorUnit(connector_env)
        # returns an instance of ModelUnit with a new connector_env
        # for the different model
        new_unit = unit.unit_for(ModelUnit, model='res.partner')
        self.assertEqual(type(new_unit), ModelUnit)
        self.assertNotEqual(new_unit.connector_env, connector_env)
        self.assertEqual(new_unit.connector_env.model_name, 'res.partner')

        backend.get_class.return_value = ModelBinder
        # returns an instance of ModelBinder with a new connector_env
        # for the different model
        new_unit = unit.binder_for(model='res.partner')
        self.assertEqual(type(new_unit), ModelBinder)
        self.assertNotEqual(new_unit.connector_env, connector_env)
        self.assertEqual(new_unit.connector_env.model_name, 'res.partner')


class TestConnectorUnitTransaction(common.TransactionCase):

    def test_instance(self):

        class ModelUnit(ConnectorUnit):
            _model_name = 'res.users'

        unit = mock_connector_unit(self.env)
        self.assertEqual(unit.model, self.env['res.users'])
        self.assertEqual(unit.env, self.env)
        self.assertEqual(unit.localcontext, self.env.context)


class TestConnectorEnvironment(unittest.TestCase):

    def test_create_environment_no_connector_env(self):
        backend_record = mock.Mock(name='BackendRecord')
        backend = mock.Mock(name='Backend')
        backend_record.get_backend.return_value = backend
        backend_record.env = mock.MagicMock(name='Environment')
        model = 'res.user'

        connector_env = ConnectorEnvironment.create_environment(
            backend_record, model
        )

        self.assertEqual(type(connector_env), ConnectorEnvironment)

    def test_create_environment_existing_connector_env(self):

        class MyConnectorEnvironment(ConnectorEnvironment):
            _propagate_kwargs = ['api']

            def __init__(self, backend_record, model_name, api=None):
                super(MyConnectorEnvironment, self).__init__(backend_record,
                                                             model_name)
                self.api = api

        backend_record = mock.Mock(name='BackendRecord')
        backend = mock.Mock(name='Backend')
        backend_record.get_backend.return_value = backend
        backend_record.env = mock.MagicMock(name='Environment')
        model = 'res.user'

        cust_env = MyConnectorEnvironment(backend_record, model,
                                          api=api)

        new_env = cust_env.create_environment(backend_record, model,
                                              connector_env=cust_env)

        self.assertEqual(type(new_env), MyConnectorEnvironment)
        self.assertEqual(new_env.api, api)


class TestAdvisoryLock(common.TransactionCase):

    def setUp(self):
        super(TestAdvisoryLock, self).setUp()
        self.registry2 = RegistryManager.get(common.get_db_name())
        self.cr2 = self.registry2.cursor()
        self.env2 = api.Environment(self.cr2, self.env.uid, {})

        @self.addCleanup
        def reset_cr2():
            # rollback and close the cursor, and reset the environments
            self.env2.reset()
            self.cr2.rollback()
            self.cr2.close()

    def test_concurrent_import_lock(self):
        """ A 2nd concurrent transaction must retry """
        lock = 'import_record({}, {}, {}, {})'.format(
            'backend.name',
            1,
            'res.partner',
            '999999',
        )
        connector_unit = mock_connector_unit(self.env)
        connector_unit.advisory_lock_or_retry(lock)
        connector_unit2 = mock_connector_unit(self.env2)
        with self.assertRaises(RetryableJobError) as cm:
            connector_unit2.advisory_lock_or_retry(lock, retry_seconds=3)
            self.assertEquals(cm.exception.seconds, 3)
