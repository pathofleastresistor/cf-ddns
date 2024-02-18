from unittest.mock import patch
import update
import requests
import pytest

def test_valid_ipv4():
    assert update.is_valid_ip("192.168.1.1")
    
def test_invalid_ipv4():
    assert not update.is_valid_ip("not_an_ip")

# def test_private_ipv4():
#     assert not update.is_valid_ip("10.0.0.1") 

@patch('update.requests.get')
def test_successful_fetch(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {'ip': '123.45.67.89'}
    assert update.get_public_ip() == '123.45.67.89'

@patch('update.requests.get')
def test_fetch_failure(mock_get):
    mock_get.side_effect = requests.RequestException()
    with pytest.raises(Exception):  # Expect the function to raise an exception
        update.get_public_ip()