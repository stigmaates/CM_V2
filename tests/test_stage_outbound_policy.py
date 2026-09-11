import pytest

from app.services import outbound_policy as policy


@pytest.fixture
def blocked(monkeypatch, tmp_path):
    monkeypatch.setattr(policy, 'STOP_FILE', tmp_path / '.stage-no-outbound')
    policy.STOP_FILE.touch()
    monkeypatch.delenv('DISABLE_OUTBOUND_MESSAGES', raising=False)


def test_switch_is_local_and_default_allows_production(monkeypatch, tmp_path):
    monkeypatch.setattr(policy, 'STOP_FILE', tmp_path / 'absent')
    monkeypatch.delenv('DISABLE_OUTBOUND_MESSAGES', raising=False)
    policy.ensure_outbound_allowed()
    monkeypatch.setenv('DISABLE_OUTBOUND_MESSAGES', 'true')
    with pytest.raises(ValueError, match='отключены'):
        policy.ensure_outbound_allowed()


def test_copied_queue_workers_return_before_database_or_locks(blocked, monkeypatch):
    from scripts import process_auto_mailings, process_mailings, process_referrals, process_topup_bonuses
    def forbidden(*args, **kwargs):
        pytest.fail('Blocked stage must not open database or send requests')
    for module in (process_mailings, process_auto_mailings, process_topup_bonuses, process_referrals):
        monkeypatch.setattr(module, 'get_db_connection', forbidden)
    process_mailings.main()
    process_mailings.process_one_mailing(None, 123)
    process_referrals.main()
    assert process_auto_mailings.process_auto_mailings()['skipped'] == 'outbound_disabled'
    assert process_topup_bonuses.process_topup_bonuses() == []


def test_transports_block_before_network_and_recipient_lookup(blocked):
    from app.services import cm_bonuses, first_visit_survey, prize_claims, tech_alerts
    from scripts import process_mailings
    with pytest.raises(ValueError, match='отключены'):
        process_mailings.tg_request('sendMessage', {'chat_id': 123})
    assert not first_visit_survey.send_first_visit_survey_invite(None, 1, 'test')
    assert cm_bonuses._notify_admin_chat(None, 10, 1)[0] is False
    assert prize_claims._notify_claim_admin_chat(None)[0] is False
    def forbidden(*args, **kwargs):
        pytest.fail('HTTP must not be called')
    assert tech_alerts.send_telegram_message('test', token='fake', chat_id='123', http_post=forbidden)[0] is False


def test_mailing_creation_blocks_before_awards_or_database(blocked):
    from app.services import mailing
    with pytest.raises(ValueError, match='отключены'):
        mailing.create_mailing(None, 1, None, [], 'test', 'HTML', [])
    with pytest.raises(ValueError, match='отключены'):
        mailing.create_bonus_giveaway(None, 1, [], 100, 'test')


def test_bots_cannot_start_polling(blocked):
    from bot import admin_main, main
    for entry in (admin_main.main, main.main):
        with pytest.raises(ValueError, match='отключены'):
            entry()
