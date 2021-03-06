""" Tests for handler functions. """
from time import time

import jwt
import mock
from django.conf import settings
from django.test import TestCase, override_settings
from oscar.test.factories import UserFactory
from waffle.testutils import override_switch

from ecommerce.extensions.api.handlers import jwt_decode_handler


def generate_jwt_token(payload, signing_key):
    """Generate a valid JWT token for authenticated requests."""
    return jwt.encode(payload, signing_key).decode('utf-8')


def generate_jwt_payload(user, issuer_name):
    """Generate a valid JWT payload given a user."""
    now = int(time())
    ttl = 5
    return {
        'iss': issuer_name,
        'username': user.username,
        'email': user.email,
        'iat': now,
        'exp': now + ttl
    }


class JWTDecodeHandlerTests(TestCase):
    """ Tests for the `jwt_decode_handler` utility function. """

    def setUp(self):
        super(JWTDecodeHandlerTests, self).setUp()
        self.user = UserFactory()

    @override_settings(
        JWT_AUTH={
            'JWT_ISSUERS': [{
                'AUDIENCE': 'test-audience',
                'ISSUER': 'test-issuer',
                'SECRET_KEY': 'test-secret-key',
            }],
            'JWT_VERIFY_AUDIENCE': False,
        }
    )
    @mock.patch('edx_django_utils.monitoring.set_custom_metric')
    def test_decode_success_edx_drf_extensions(self, mock_set_custom_metric):
        """
        Should pass using the edx-drf-extensions jwt_decode_handler.

        This would happen with the combination of the JWT_ISSUERS configured in
        the way that edx-drf-extensions is expected, and using the secret-key
        of the first configured issuer.
        """
        first_issuer = settings.JWT_AUTH['JWT_ISSUERS'][0]
        payload = generate_jwt_payload(self.user, issuer_name=first_issuer['ISSUER'])
        token = generate_jwt_token(payload, first_issuer['SECRET_KEY'])
        self.assertDictContainsSubset(payload, jwt_decode_handler(token))
        mock_set_custom_metric.assert_called_with('ecom_jwt_decode_handler', 'edx-drf-extensions')

    @override_settings(
        JWT_AUTH={
            'JWT_ISSUERS': [
                {
                    'AUDIENCE': 'test-audience',
                    'ISSUER': 'test-issuer',
                    'SECRET_KEY': 'test-secret-key',
                },
                {
                    'AUDIENCE': 'test-audience',
                    'ISSUER': 'test-invalid-issuer',
                    'SECRET_KEY': 'test-secret-key-2',
                },
                {
                    'AUDIENCE': 'test-audience',
                    'ISSUER': 'test-issuer-2',
                    'SECRET_KEY': 'test-secret-key-2',
                },
            ],
            'JWT_VERIFY_AUDIENCE': False,
        }
    )
    @override_switch('jwt_decode_handler.log_exception.edx-drf-extensions', active=True)
    @mock.patch('edx_django_utils.monitoring.set_custom_metric')
    @mock.patch('ecommerce.extensions.api.handlers.logger')
    def test_decode_success_multiple_issuers(self, mock_logger, mock_set_custom_metric):
        """
        Should pass using ``_ecommerce_jwt_decode_handler_multiple_issuers``.

        This would happen with the combination of the JWT_ISSUERS configured in
        the way that edx-drf-extensions is expected, but when the token was
        generated from the second (or third+) issuer.
        """
        non_first_issuer = settings.JWT_AUTH['JWT_ISSUERS'][2]
        payload = generate_jwt_payload(self.user, issuer_name=non_first_issuer['ISSUER'])
        token = generate_jwt_token(payload, non_first_issuer['SECRET_KEY'])
        self.assertDictContainsSubset(payload, jwt_decode_handler(token))
        mock_set_custom_metric.assert_called_with('ecom_jwt_decode_handler', 'ecommerce-multiple-issuers')
        mock_logger.exception.assert_not_called()
        mock_logger.warning.assert_not_called()
        mock_logger.error.assert_not_called()
        mock_logger.info.assert_called_with('Failed to use edx-drf-extensions jwt_decode_handler.', exc_info=True)

    @override_settings(
        JWT_AUTH={
            'JWT_ISSUERS': [
                {
                    'AUDIENCE': 'test-audience',
                    'ISSUER': 'test-issuer',
                    'SECRET_KEY': 'test-secret-key',
                },
                {
                    'AUDIENCE': 'test-audience',
                    'ISSUER': 'test-issuer-2',
                    'SECRET_KEY': 'test-secret-key-2',
                },
            ],
            'JWT_VERIFY_AUDIENCE': False,
        }
    )
    @override_switch('jwt_decode_handler.log_exception.ecommerce-multiple-issuers', active=True)
    @mock.patch('ecommerce.extensions.api.handlers.logger')
    def test_decode_error_invalid_token(self, mock_logger):
        """
        Should fail ``_ecommerce_jwt_decode_handler_multiple_issuers`` due to
        invalid token, not because it is not configured properly.
        """
        # Update the payload to ensure a validation error
        payload = generate_jwt_payload(self.user, issuer_name='test-issuer-2')
        payload['exp'] = 0
        token = generate_jwt_token(payload, 'test-secret-key-2')
        with self.assertRaisesMessage(
            jwt.InvalidTokenError,
            (
                "All combinations of JWT issuers with updated config failed to validate the token. "
                "Wrong secret_key for issuer test-issuer. Invalid token found using issuer test-issuer-2."
            )
        ):
            jwt_decode_handler(token)

            mock_logger.exception.assert_called_with('Custom config JWT decode failed!')
            mock_logger.info.assert_called_with(
                'Failed to use ecommerce multiple issuer jwt_decode_handler.',
                exc_info=True,
            )
