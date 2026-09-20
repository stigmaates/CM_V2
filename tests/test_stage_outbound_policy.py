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


def test_stage_topup_sync_can_create_approvals_without_sending(blocked, monkeypatch):
    from scripts import process_topup_bonuses

    monkeypatch.setattr(process_topup_bonuses, "_enabled_club_ids", lambda club_id=None: [club_id or 2])
    monkeypatch.setattr(process_topup_bonuses, "start_job_run", lambda *args, **kwargs: 7)
    monkeypatch.setattr(process_topup_bonuses, "finish_job_run", lambda *args, **kwargs: None)

    class Lock:
        acquired = True

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(process_topup_bonuses, "job_lock", lambda *args, **kwargs: Lock())
    calls = []
    monkeypatch.setattr(
        process_topup_bonuses,
        "process_topup_bonus_awards",
        lambda club_id, send_message: calls.append((club_id, send_message))
        or {"pending_approval": 1, "awarded": 0, "sent": 0, "failed": 0, "skipped": 0},
    )

    result = process_topup_bonuses.process_topup_bonuses(2, create_approvals_when_blocked=True)

    assert result[0]["pending_approval"] == 1
    assert calls == [(2, None)]


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


def test_admin_bot_override_does_not_unblock_other_outbound(blocked, monkeypatch):
    monkeypatch.setenv('ALLOW_STAGE_ADMIN_BOT', '1')

    policy.ensure_admin_bot_allowed()
    with pytest.raises(ValueError, match='отключены'):
        policy.ensure_outbound_allowed()


def test_guest_bot_override_does_not_unblock_other_outbound(blocked, monkeypatch):
    monkeypatch.setenv('ALLOW_STAGE_GUEST_BOT', '1')

    policy.ensure_guest_bot_allowed()
    with pytest.raises(ValueError, match='отключены'):
        policy.ensure_outbound_allowed()


def test_manual_mailing_override_is_scoped_and_does_not_remove_stage_stop(blocked, monkeypatch):
    monkeypatch.setenv(policy.MANUAL_MAILING_OVERRIDE_ENV, "1")

    assert policy.manual_mailings_only() is True
    with pytest.raises(ValueError, match="отключены"):
        policy.ensure_outbound_allowed()

    with policy.allow_manual_mailing_outbound():
        policy.ensure_outbound_allowed()

    with pytest.raises(ValueError, match="отключены"):
        policy.ensure_outbound_allowed()


def test_auto_workers_remain_blocked_when_manual_mailings_are_allowed(blocked, monkeypatch):
    from scripts import process_auto_mailings

    monkeypatch.setenv(policy.MANUAL_MAILING_OVERRIDE_ENV, "1")

    assert process_auto_mailings.process_auto_mailings()["skipped"] == "outbound_disabled"
