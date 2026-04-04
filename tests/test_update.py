from unittest.mock import patch
import update
import requests
import pytest


def test_valid_public_ipv4():
    assert update.is_valid_ip("1.1.1.1")

def test_invalid_ipv4():
    assert not update.is_valid_ip("not_an_ip")

def test_invalid_octet_range():
    assert not update.is_valid_ip("999.999.999.999")

def test_private_ipv4_10():
    assert not update.is_valid_ip("10.0.0.1")

def test_private_ipv4_192():
    assert not update.is_valid_ip("192.168.1.1")

def test_loopback_ipv4():
    assert not update.is_valid_ip("127.0.0.1")


@patch('update.requests.get')
def test_successful_fetch(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {'ip': '1.1.1.1'}
    assert update.get_public_ip() == '1.1.1.1'

@patch('update.requests.get')
def test_fetch_failure(mock_get):
    mock_get.side_effect = requests.RequestException()
    with pytest.raises(Exception):
        update.get_public_ip()


@patch('update.requests.get')
def test_get_zones_filtered(mock_get):
    mock_get.return_value.json.return_value = {
        'result': [
            {'name': 'example.com', 'id': 'zone1'},
            {'name': 'other.com', 'id': 'zone2'},
        ]
    }
    zones = update.get_zones(['example.com'])
    assert zones == {'example.com': 'zone1'}

@patch('update.requests.get')
def test_get_zones_unfiltered(mock_get):
    mock_get.return_value.json.return_value = {
        'result': [
            {'name': 'example.com', 'id': 'zone1'},
            {'name': 'other.com', 'id': 'zone2'},
        ]
    }
    zones = update.get_zones()
    assert zones == {'example.com': 'zone1', 'other.com': 'zone2'}


@patch('update.requests.get')
def test_fetch_dns_records_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        'result': [{'name': 'example.com', 'content': '1.2.3.4', 'id': 'rec1'}]
    }
    records = update.fetch_dns_records('zone1')
    assert len(records) == 1
    assert records[0]['content'] == '1.2.3.4'

@patch('update.requests.get')
def test_fetch_dns_records_failure(mock_get):
    mock_get.return_value.status_code = 500
    records = update.fetch_dns_records('zone1')
    assert records == []


def test_should_update_record_ip_changed():
    record = {'content': '1.2.3.4'}
    assert update.should_update_record('5.6.7.8', record)

def test_should_update_record_ip_unchanged():
    record = {'content': '1.2.3.4'}
    assert not update.should_update_record('1.2.3.4', record)

@patch('update.FORCE_UPDATE', True)
def test_should_update_record_force():
    record = {'content': '1.2.3.4'}
    assert update.should_update_record('1.2.3.4', record)


@patch('update.requests.put')
def test_update_dns_record_success(mock_put):
    mock_put.return_value.status_code = 200
    update.update_dns_record('zone1', 'rec1', {'name': 'example.com', 'content': '1.2.3.4'})
    mock_put.assert_called_once()

@patch('update.DRY_RUN', True)
@patch('update.requests.put')
def test_update_dns_record_dry_run(mock_put):
    update.update_dns_record('zone1', 'rec1', {'name': 'example.com', 'content': '1.2.3.4'})
    mock_put.assert_not_called()
