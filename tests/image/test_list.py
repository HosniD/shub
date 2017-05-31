import json

import mock
import pytest
from click.testing import CliRunner

from shub.exceptions import  BadParameterException, ShubException
from shub.image.list import cli
from shub.image.list import _run_cmd_in_docker_container
from shub.image.list import _extract_metadata_from_image_info_output


def _mock_docker_client(wait_code=0, logs=b''):
    client_mock = mock.Mock()
    client_mock.create_container.return_value = {'Id': '1234'}
    client_mock.wait.return_value = wait_code
    client_mock.logs.return_value = logs
    return client_mock


def _get_settings_mock(settings=None):
    settings_mock = mock.Mock()
    settings_mock.json.return_value = settings or {}
    return settings_mock


def test_cli_no_scrapinghub_config():
    result = CliRunner().invoke(cli, ["dev", "-v", "--version", "test"])
    assert result.exit_code == BadParameterException.exit_code
    assert 'Could not find target "dev"' in result.output


@pytest.mark.usefixtures('project_dir')
@mock.patch('shub.image.utils.get_docker_client')
@mock.patch('requests.get')
def test_cli(requests_get_mock, get_docker_client_mock):
    """Case when shub-image-info succeeded."""
    requests_get_mock.return_value = _get_settings_mock()
    docker_client = _mock_docker_client(logs=b'{"spiders": ["abc","def"]}')
    get_docker_client_mock.return_value = docker_client
    result = CliRunner().invoke(cli, ["dev", "-v", "-s", "--version", "test"])
    assert result.exit_code == 0
    assert result.output.endswith('abc\ndef\n')
    requests_get_mock.assert_called_with(
        'https://app.scrapinghub.com/api/settings/get.json',
        allow_redirects=False, auth=('abcdef', ''),
        params={'project': 12345}, timeout=300)


@pytest.mark.usefixtures('project_dir')
@mock.patch('shub.image.utils.get_docker_client')
@mock.patch('requests.get')
def test_cli_image_info_error(requests_get_mock, get_docker_client_mock):
    """Case when shub-image-info command failed with unknown exit code."""
    requests_get_mock.return_value = _get_settings_mock()
    docker_client = _mock_docker_client(wait_code=1, logs=b'some-error')
    get_docker_client_mock.return_value = docker_client
    result = CliRunner().invoke(cli, ["dev", "-v", "--version", "test"])
    assert result.exit_code == 1
    assert 'Container with shub-image-info cmd exited with code 1' in result.output


@pytest.mark.usefixtures('project_dir')
@mock.patch('shub.image.utils.get_docker_client')
@mock.patch('requests.get')
def test_cli_image_info_not_found(requests_get_mock, get_docker_client_mock):
    """Case when shub-image-info cmd not found with fallback to list-spiders."""
    requests_get_mock.return_value = _get_settings_mock({'SETTING': 'VALUE'})
    docker_client = _mock_docker_client()
    docker_client.wait.side_effect = [127, 0]
    docker_client.logs.side_effect = ["not-found", "spider1\nspider2\n"]
    get_docker_client_mock.return_value = docker_client
    result = CliRunner().invoke(cli, ["dev", "-v", "--version", "test"])
    assert result.exit_code == 0
    assert 'spider1\nspider2' in result.output


@pytest.mark.usefixtures('project_dir')
@mock.patch('shub.image.utils.get_docker_client')
@mock.patch('requests.get')
def test_cli_both_commands_failed(requests_get_mock, get_docker_client_mock):
    """Case when shub-image-info cmd not found with fallback to list-spiders."""
    requests_get_mock.return_value = _get_settings_mock({'SETTING': 'VALUE'})
    docker_client = _mock_docker_client(wait_code=127, logs=b'not-found')
    get_docker_client_mock.return_value = docker_client
    result = CliRunner().invoke(cli, ["dev", "-v", "--version", "test"])
    assert result.exit_code == 1
    assert 'Container with list cmd exited with code 127' in result.output


@mock.patch('shub.image.utils.get_docker_client')
def test_run_cmd_in_docker_container(get_docker_client_mock):
    docker_client = _mock_docker_client(logs='abc\ndef\ndsd')
    get_docker_client_mock.return_value = docker_client
    test_env = {'TEST_ENV1': 'VAL1', 'TEST_ENV2': 'VAL2'}
    result = _run_cmd_in_docker_container('image', 'test-cmd', test_env)
    assert result[0] == 0
    assert result[1] == 'abc\ndef\ndsd'
    docker_client.create_container.assert_called_with(
        command=['test-cmd'], environment=test_env, image='image')
    docker_client.start.assert_called_with({'Id': '1234'})
    docker_client.wait.assert_called_with(container="1234")
    docker_client.logs.assert_called_with(
        container='1234', stderr=False, stdout=True,
        stream=False, timestamps=False)


@pytest.mark.parametrize('output,error_msg',[
    ('bad-json', 'output is not a valid JSON'),
    (json.dumps([]), 'output is not a valid JSON dict'),
    (json.dumps({'spiders': 'spider'}), 'spiders section must be a list'),
    (json.dumps({'spiders': ['']}), "spider name can't be empty or non-string"),
    (json.dumps({'spiders': [123]}), "spider name can't be empty or non-string"),
])
def test_extract_metadata_from_image_info_output_failures(output, error_msg):
    with pytest.raises(ShubException) as exc:
        _extract_metadata_from_image_info_output(output)
    assert error_msg in exc.value.message
