from unittest import mock

from directory_constants import choices
from directory_forms_api_client import actions
from directory_forms_api_client.helpers import Sender
import pytest
import requests

from django.core.cache import cache
from django.urls import reverse

from core import constants, forms, helpers, views
from core.tests.helpers import create_response, submit_step_factory


@pytest.fixture
def submit_step(client):
    return submit_step_factory(client=client, view_class=views.Wizard, url_name='wizard')


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()


@pytest.fixture(autouse=True)
def mock_lookup_commodity_code_by_name():
    response = create_response({'results': [{'description': 'Example', 'commodity_code': '1234'}]})
    patch = mock.patch.object(helpers, 'lookup_commodity_code_by_name', return_value=response)
    yield patch.start()
    patch.stop()


@pytest.fixture
def steps_data(captcha_stub):
    return {
        views.TYPE: {'choice': constants.UK_BUSINESS},
        views.PRODUCT: {'commodities': 'Foo'},
        views.IMPACT: {
            'sale_volume_expected': 1,
            'production_levels_expected': 2,
            'profitability_expected': 3,
            'employment_expected': 4,
        },
        views.TARIFF_COMMENT: {'other_tariff_related_changes': 'Bar'},
        views.NON_TARIFF_COMMENT: {'other_non_tariff_related_changes': 'Baz'},
        views.OUTCOME: {'outcome': constants.INCREASE},
        views.BUSINESS: {
            'company_name': 'Jim Ham',
            'company_number': '1234567',
            'sector': forms.INDUSTRY_CHOICES[1][0],
            'percentage_uk_market': 2,
            'employees': choices.EMPLOYEES[0][0],
            'turnover': forms.TURNOVER_CHOICES[0][0],
        },
        views.PERSONAL: {
            'given_name': 'Jim',
            'family_name': 'Example',
            'email': 'jim@example.com',
        },
        views.SUMMARY: {
            'terms_agreed': True,
            'g-recaptcha-response': captcha_stub,
        }
    }


def test_landing_page(client):
    url = reverse('landing-page')
    response = client.get(url)

    assert response.status_code == 200
    assert response.template_name == [views.LandingPage.template_name]


def test_companies_house_search_no_term(client):
    url = reverse('companies-house-search')
    response = client.get(url)

    assert response.status_code == 400


@mock.patch('core.views.ch_search_api_client.company.search_companies')
def test_companies_house_search_api_error(mock_search, client, settings):
    mock_search.return_value = create_response(status_code=400)
    url = reverse('companies-house-search')

    with pytest.raises(requests.HTTPError):
        client.get(url, data={'term': 'thing'})


@mock.patch('core.views.ch_search_api_client.company.search_companies')
def test_companies_house_search_api_success(mock_search, client, settings):

    mock_search.return_value = create_response({'items': [{'name': 'Smashing corp'}]})
    url = reverse('companies-house-search')

    response = client.get(url, data={'term': 'thing'})

    assert response.status_code == 200
    assert response.content == b'[{"name":"Smashing corp"}]'


@mock.patch.object(helpers, 'search_hierarchy')
@mock.patch('captcha.fields.ReCaptchaField.clean', mock.Mock)
@mock.patch.object(actions, 'ZendeskAction')
def test_wizard_end_to_end(mock_zendesk_action, mock_search_hierarchy, submit_step, captcha_stub, client, steps_data):
    hierarchy = [{'key': 'foo'}]
    mock_search_hierarchy.return_value = create_response({'results': hierarchy})

    # TYPE
    response = submit_step(steps_data[views.TYPE])
    assert response.status_code == 302

    # PRODUCT
    response = client.get(response.url)
    assert response.status_code == 200
    assert response.context_data['hierarchy'] == hierarchy
    response = submit_step(steps_data[views.PRODUCT])
    assert response.status_code == 302

    # IMPACT
    response = client.get(response.url)
    assert response.status_code == 200
    response = submit_step(steps_data[views.IMPACT])
    assert response.status_code == 302

    # TARIFF COMMENT
    response = client.get(response.url)
    assert response.status_code == 200
    response = submit_step(steps_data[views.TARIFF_COMMENT])
    assert response.status_code == 302

    # NON TARIFF COMMENT
    response = client.get(response.url)
    assert response.status_code == 200
    response = submit_step(steps_data[views.NON_TARIFF_COMMENT])
    assert response.status_code == 302

    # OUTCOME
    response = client.get(response.url)
    assert response.status_code == 200
    response = submit_step(steps_data[views.OUTCOME])
    assert response.status_code == 302

    # BUSINESS
    response = client.get(response.url)
    assert response.status_code == 200
    response = submit_step(steps_data[views.BUSINESS])
    assert response.status_code == 302

    # PERSONAL
    response = client.get(response.url)
    assert response.status_code == 200
    response = submit_step(steps_data[views.PERSONAL])
    assert response.status_code == 302

    # SUMMARY
    response = client.get(response.url)
    assert response.status_code == 200
    assert response.context_data['all_cleaned_data']

    response = submit_step(steps_data[views.SUMMARY])
    assert response.status_code == 302

    # FINISH
    response = client.get(response.url)

    assert response.status_code == 302
    assert response.url == views.Wizard.success_url
    assert mock_zendesk_action.call_count == 1
    assert mock_zendesk_action.call_args == mock.call(
        subject='ERP form was submitted',
        full_name='Jim Example',
        service_name='erp',
        email_address='jim@example.com',
        form_url=reverse('wizard', kwargs={'step': views.TYPE}),
        form_session=mock.ANY,
        sender=Sender(
            email_address='jim@example.com',
            country_code=None,
        ),
    )
    assert mock_zendesk_action().save.call_count == 1
    assert mock_zendesk_action().save.call_args == mock.call({
        'choice': constants.UK_BUSINESS,
        'commodities': 'Foo',
        'sale_volume_actual': '',
        'sale_volume_expected': '1',
        'production_levels_actual': '',
        'production_levels_expected': '2',
        'profitability_actual': '',
        'profitability_expected': '3',
        'employment_actual': '',
        'employment_expected': '4',
        'other_tariff_related_changes': 'Bar',
        'other_non_tariff_related_changes': 'Baz',
        'outcome': constants.INCREASE,
        'company_name': 'Jim Ham',
        'company_number': '1234567',
        'sector': forms.INDUSTRY_CHOICES[1][0],
        'percentage_uk_market': '2',
        'employees': choices.EMPLOYEES[0][0],
        'turnover': forms.TURNOVER_CHOICES[0][0],
        'given_name': 'Jim',
        'family_name': 'Example',
        'email': 'jim@example.com'
    })


def test_wizard_save_for_later(submit_step, steps_data):
    expected_url = reverse("save-for-later")

    response = submit_step(steps_data[views.TYPE])
    assert response.status_code == 302

    response = submit_step(steps_data[views.PRODUCT])
    assert response.status_code == 302

    response = submit_step(steps_data[views.IMPACT])
    assert response.status_code == 302

    response = submit_step(steps_data[views.TARIFF_COMMENT])
    assert response.status_code == 302

    response = submit_step({'wizard_save_for_later': True, **steps_data[views.NON_TARIFF_COMMENT]})
    assert response.status_code == 302
    assert response.url == f'{expected_url}?step={views.NON_TARIFF_COMMENT}'


def test_save_for_later_no_cache_key(client):
    url = reverse('save-for-later')
    response = client.get(url)

    assert response.status_code == 404


def test_save_for_later(client, steps_data, submit_step):
    # visit the wizard to create cache entry
    response = submit_step({**steps_data[views.TYPE], 'wizard_save_for_later': True})
    assert response.status_code == 302

    url = reverse('save-for-later')
    response = client.get(url)

    assert response.status_code == 200
    assert response.template_name == [views.SaveForLaterFormView.template_name]


@mock.patch('core.helpers.search_hierarchy')
def test_select_product(mock_search_hierarchy, client, steps_data, submit_step):
    mock_search_hierarchy.return_value = create_response({'results': []})
    response = submit_step(steps_data[views.TYPE])
    assert response.status_code == 302

    response = submit_step({**steps_data[views.PRODUCT], 'wizard_select_product': 'Bar'})
    assert response.status_code == 302

    response = client.get(reverse('wizard', kwargs={'step': views.PRODUCT}))
    assert response.status_code == 200
    commodities = response.context_data['form'].data['product-search-commodities'].split(views.PRODUCT_DELIMITER)
    assert sorted(commodities) == ['Bar', 'Foo']


@mock.patch('core.helpers.search_hierarchy')
def test_deselect_product(mock_search_hierarchy, client, steps_data, submit_step):
    mock_search_hierarchy.return_value = create_response({'results': []})
    response = submit_step(steps_data[views.TYPE])
    assert response.status_code == 302

    response = submit_step({**steps_data[views.PRODUCT], 'wizard_remove_selected_product': 'Foo'})
    assert response.status_code == 302

    response = client.get(reverse('wizard', kwargs={'step': views.PRODUCT}))
    assert response.status_code == 200
    assert response.context_data['form'].data['product-search-commodities'] == ''


def test_browse_product(client, steps_data, submit_step):
    response = submit_step(steps_data[views.TYPE])
    assert response.status_code == 302

    response = submit_step({**steps_data[views.PRODUCT], 'wizard_browse_product': 'root'})
    assert response.status_code == 302

    url = reverse('wizard', kwargs={'step': views.PRODUCT})
    assert response.url == f'{url}?node_id=root#root'


def test_save_for_later_validation_validation_error(client, steps_data, submit_step):
    # visit the wizard to create cache entry
    response = submit_step({**steps_data[views.TYPE], 'wizard_save_for_later': True})
    assert response.status_code == 302

    # visit the wizard and create cache entry
    url = reverse('save-for-later')
    response = client.post(url)

    assert response.status_code == 200
    assert response.context_data['form'].is_valid() is False


@mock.patch.object(views.SaveForLaterFormView.form_class, 'save')
def test_save_for_later_validation_submit_success(mock_save, settings, client,  steps_data, submit_step):
    # visit the wizard to create cache entry
    response = submit_step({**steps_data[views.TYPE], 'wizard_save_for_later': True})
    assert response.status_code == 302

    mock_save.return_value = create_response()
    url = reverse('save-for-later')
    data = {'email': 'test@example.com'}
    response = client.post(url, data)

    assert response.status_code == 302
    assert response.url == views.SaveForLaterFormView.success_url
    assert mock_save.call_count == 1
    assert mock_save.call_args == mock.call(
        template_id=settings.GOV_NOTIFY_TEMPLATE_SAVE_FOR_LATER,
        email_address=data['email'],
        form_url=url,
    )

    response = client.get(response.url)

    for message in response.context['messages']:
        assert str(message) == views.SaveForLaterFormView.success_message


def test_commodity_search_no_term(client):
    url = reverse('commodity-search')
    response = client.get(url)

    assert response.status_code == 400


def test_commodity_search_api_error(mock_lookup_commodity_code_by_name, client, settings):
    mock_lookup_commodity_code_by_name.return_value = create_response(status_code=400)
    url = reverse('commodity-search')

    with pytest.raises(requests.HTTPError):
        client.get(url, data={'term': 'thing'})


def test_commodity_search_api_success(mock_lookup_commodity_code_by_name, client, settings):
    url = reverse('commodity-search')

    response = client.get(url, data={'term': 'thing'})

    assert response.status_code == 200
    assert response.content == b'[{"text":"Example","value":"1234"}]'
    assert mock_lookup_commodity_code_by_name.call_count == 1
    assert mock_lookup_commodity_code_by_name.call_args == mock.call(query='thing')
