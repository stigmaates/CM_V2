from flask import flash, redirect, render_template, request, session, url_for

from app.core import owner_required
from app.services.prize_claims import (
    cancel_prize_claim_by_owner,
    get_prize_claims_for_owner,
    mark_prize_claim_issued_by_owner,
)

from . import owner_bp


@owner_bp.route('/prize-claims')
@owner_required
def prize_claims():
    club_id = session.get('club_id')
    if not club_id:
        flash('Сначала создайте клуб', 'error')
        return redirect(url_for('owner.club_create'))

    status = request.args.get('status', 'all').strip() or 'all'
    claims = get_prize_claims_for_owner(int(club_id), status=status, limit=200)
    return render_template('owner/prize_claims.html', claims=claims, selected_status=status)


@owner_bp.route('/prize-claims/<int:claim_id>/issue', methods=['POST'])
@owner_required
def prize_claim_issue(claim_id):
    club_id = session.get('club_id')
    if not club_id:
        flash('Сначала создайте клуб', 'error')
        return redirect(url_for('owner.club_create'))

    result = mark_prize_claim_issued_by_owner(
        claim_id=claim_id,
        club_id=int(club_id),
        user_id=session.get('user_id'),
    )
    flash('Приз отмечен как выдан' if result.get('ok') else 'Не удалось изменить статус приза', 'success' if result.get('ok') else 'error')
    return redirect(url_for('owner.prize_claims', status=request.args.get('status', 'all')))


@owner_bp.route('/prize-claims/<int:claim_id>/cancel', methods=['POST'])
@owner_required
def prize_claim_cancel(claim_id):
    club_id = session.get('club_id')
    if not club_id:
        flash('Сначала создайте клуб', 'error')
        return redirect(url_for('owner.club_create'))

    reason = request.form.get('reason', '').strip() or None
    result = cancel_prize_claim_by_owner(
        claim_id=claim_id,
        club_id=int(club_id),
        reason=reason,
        user_id=session.get('user_id'),
    )
    flash('Заявка на приз отменена' if result.get('ok') else 'Не удалось отменить заявку', 'success' if result.get('ok') else 'error')
    return redirect(url_for('owner.prize_claims', status=request.args.get('status', 'all')))
