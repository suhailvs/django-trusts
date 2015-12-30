import os
import json
import unittest
import settings
from decimal import Decimal
from urllib import urlencode
from urlparse import urlparse
from datetime import date, datetime, timedelta

from django.apps import apps
from django.db import models
from django.db.models.base import ModelBase
from django.db import connection
from django.core.management.color import no_style
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth.management import create_permissions
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.management import update_all_contenttypes, update_contenttypes
from django.test.testcases import TestCase
from django.test.client import MULTIPART_CONTENT, Client

from trusts.models import Trust, TrustManager, ContentMixin
from trusts.backends import TrustModelBackend

class ContentMixinTestCase(TestCase):
    """
    Base class for tests of model mixins. To use, subclass and specify
    the mixin class variable. A model using the mixin will be made
    available in self.model.
    """

    mixin = ContentMixin

    def mock_mixin_model(self):
        # Create a dummy model which extends the mixin
        self.model = ModelBase('TestModel' + self.mixin.__name__, (self.mixin,),
            {'__module__': self.mixin.__module__})
        self.model.id = models.AutoField(primary_key=True)

        # Create the schema for our test model
        self._style = no_style()
        sql, _ = connection.creation.sql_create_model(self.model, self._style)

        with connection.cursor() as c:
            for statement in sql:
                c.execute(statement)

        app_config = apps.get_app_config(self.mixin._meta.app_label)
        update_contenttypes(app_config, verbosity=1, interactive=False)
        create_permissions(app_config, verbosity=1, interactive=False)

    def delete_mixin_model(self):
        # Delete the schema for the test model
        sql = connection.creation.sql_destroy_model(self.model, (), self._style)

        with connection.cursor() as c:
            for statement in sql:
                c.execute(statement)

    def create_test_users(self):
        # Create a user.
        self.username = 'daniel'
        self.password = 'pass'
        self.user = User.objects.create_user(self.username, 'daniel@example.com', self.password)
        self.user.is_active = True
        self.user.save()

        # Create another
        self.name1 = 'anotheruser'
        self.pass1 = 'pass'
        self.user1 = User.objects.create_user(self.name1, 'another@example.com', self.pass1)
        self.user1.is_active = True
        self.user1.save()

    def delete_test_users(self):
        self.user.delete()
        self.user1.delete()

    def create_test_fixtures(self):
        self.trust = Trust(settlor=self.user)
        self.trust.save()

        self.trust1 = Trust(settlor=self.user1)
        self.trust1.save()

        self.group = Group(name="Test Group")
        self.group.save()

        self.content = self.model()
        self.content.trust = self.trust
        self.content.save()

    def delete_test_fixtures(self):
        self.trust.delete()
        self.trust1.delete()

        self.group.delete()

        self.content.delete()

    def setUp(self):
        super(ContentMixinTestCase ,self).setUp()

        self.mock_mixin_model()

        self.create_test_users()

        self.create_test_fixtures()

        self.app_label = self.model._meta.app_label
        self.model_name = self.model._meta.model_name

        for codename in ['change', 'add', 'delete']:
            setattr(self, 'perm_%s' % codename,
                Permission.objects.get_by_natural_key('change_%s' % self.model_name, self.app_label, self.model_name)
            )

    def tearDown(self):
        super(ContentMixinTestCase ,self).tearDown()

        self.delete_test_fixtures()

        self.delete_test_users()

        self.delete_mixin_model()

    def assertIsIterable(self, obj, msg='Not an iterable'):
        return self.assertTrue(hasattr(obj, '__iter__'))

    def test_unknown_content(self):
        perm = TrustModelBackend().get_group_permissions(self.user, {})
        self.assertIsNotNone(perm)
        self.assertIsIterable(perm)
        self.assertEqual(len(perm), 0)

        trust = Trust.objects.get_by_content(self.user)
        self.assertIsNone(trust)

    def test_no_permission(self):
        had = self.user.has_perm(self.perm_change, self.content)
        self.assertFalse(had)

    def test_user_not_in_group_has_no_trust(self):
        self.test_no_permission()

        # reloading user to purge the _trust_perm_cache
        self.user = User._default_manager.get(pk=self.user.pk)

        self.perm_change.group_set.add(self.group)
        self.perm_change.save()

        had = self.user.has_perm(self.perm_change, self.content)
        self.assertFalse(had)

    def test_user_in_group_has_no_trust(self):
        self.test_user_not_in_group_has_no_trust()

        # reloading user to purge the _trust_perm_cache
        self.user = User._default_manager.get(pk=self.user.pk)

        self.user.groups.add(self.group)

        had = self.user.has_perm(self.perm_change, self.content)
        self.assertFalse(had)

    def test_user_in_group_has_trust(self):
        self.test_user_in_group_has_no_trust()

        # reloading user to purge the _trust_perm_cache
        self.user = User._default_manager.get(pk=self.user.pk)

        self.trust.groups.add(self.group)

        had = self.user.has_perm(self.perm_change, self.content)
        self.assertTrue(had)

    def test_has_trust(self):
        had = self.user.has_perm(self.perm_change, self.content)
        self.assertFalse(had)

        trust = Trust(settlor=self.user, title='Test trusts')
        trust.save()

        self.user.user_permissions.add(self.perm_change)
        self.trust.trustees.add(self.user)

        # reloading user to purge the _trust_perm_cache
        self.user = User._default_manager.get(pk=self.user.pk)

        had = self.user.has_perm(self.perm_change, self.content)
        self.assertTrue(had)
