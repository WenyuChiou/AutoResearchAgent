"""Backend refusal codes written as the plain-Chinese reasons of the Wiki V1 chat panel.

The page shows ``text`` and keeps ``code`` in a technical-details fold; it never
prints the raw code in the message area. Table source: design 8.4 "错误码怎么写成人话",
plus the few codes this backend adds (marked in the comments). Pure data, no I/O.
"""

FALLBACK = '对话许可没有通过核对，界面只读，发送关闭'

# (code, group, text). Exact codes win over the family rules below.
EXACT = (
    ('operator-chat-config-required', 'not-configured', '本机还没有配置对话'),
    ('chat-config-pin-differs', 'not-configured', '本机还没有配置对话'),
    ('codex-login-required', 'login', '还没登录 Codex'),
    ('chat-operator-lease-expired', 'permit-expired', '对话许可已到期，发送关闭；已用额度和原回答保留'),
    ('chat-permit-not-current', 'permit-expired', '对话许可已到期，发送关闭；已用额度和原回答保留'),
    ('chat-continuation-contract-not-current', 'permit-expired', '对话许可已到期，发送关闭；已用额度和原回答保留'),
    # Added by this backend: operator revoked the permit with the .revoked marker.
    ('chat-permit-revoked', 'permit-revoked', '对话许可已被操作者撤销，发送关闭；已用额度和原回答保留'),
    ('chat-config-changed', 'binding-changed', '配置或绑定变了，需要操作者重新核对'),
    ('chat-cumulative-budget-exhausted', 'budget-exhausted', '调用次数已用完，不会自动追加'),
    ('chat-budget-config-differs', 'budget-mismatch', '额度记录和配置对不上，发送关闭，请联系操作者'),
    ('chat-budget-owned-by-another-store', 'budget-mismatch', '额度记录和配置对不上，发送关闭，请联系操作者'),
    ('chat-another-turn-running', 'other-turn', '别处有一轮对话还没结束（或还没核对）'),
    ('chat-unresolved-turn-must-be-reconciled', 'other-turn', '别处有一轮对话还没结束（或还没核对）'),
    ('chat-native-account-binding-differs', 'account-differs', '现在登录的 Codex 账号和准备许可时的不是同一个'),
    ('chat-native-account-identity-missing', 'account-differs', '现在登录的 Codex 账号和准备许可时的不是同一个'),
    ('codex-quota-below-15', 'codex-quota', 'Codex 账号自己的额度不足 15%，或读不到额度，所以不发送'),
    ('codex-quota-unknown', 'codex-quota', 'Codex 账号自己的额度不足 15%，或读不到额度，所以不发送'),
    ('codex-requested-model-unavailable', 'model-unavailable', '许可里指定的模型或推理强度现在用不了'),
    ('codex-requested-effort-unavailable', 'model-unavailable', '许可里指定的模型或推理强度现在用不了'),
    ('credential-required', 'page-credential', '页面的登录信息失效了，请从 Wiki 首页重新打开'),
    ('chat-explicit-origin-required', 'page-credential', '页面的登录信息失效了，请从 Wiki 首页重新打开'),
    ('chat-stage-material-reader-unavailable', 'stage-unconnected', '这一段的材料还没接通，对话关着'),
    ('chat-stage-not-supported', 'stage-unconnected', '这一段的材料还没接通，对话关着'),
    ('chat-session-content-cleared-open-new-session', 'session-cleared', '对话记录已清空（或课题已变），请开新对话'),
    ('chat-project-changed-open-new-session', 'session-cleared', '对话记录已清空（或课题已变），请开新对话'),
    ('chat-message-size-invalid', 'message-size', '消息是空的，或超过 8192 字节，没有发送'),
    ('chat-idempotency-conflict', 'idempotency-conflict', '同一条消息已经发过，内容不一样，没有再发'),
    ('chat-request-not-live', 'question-card', '这个问题已经失效（那一轮结束了）'),
    ('chat-request-already-answered', 'question-card', '这个问题已经答过了'),
    ('chat-answer-question-ids-differ', 'question-card', '回答和问题对不上，请重新读取后再答'),
    ('chat-confirmation-state-changed', 'question-card', '这一轮的状态已经变了，请重新读取'),
    ('chat-continuation-reconcile-not-authorized', 'reconcile-not-authorized', '这份许可下不能核对，请联系操作者'),
    ('chat-native-connection-lost-reconcile-required', 'connection-lost', '连接断了（或服务重启过），这一轮需要核对'),
    ('host-restarted-native-terminal-unconfirmed', 'connection-lost', '连接断了（或服务重启过），这一轮需要核对'),
    ('chat-response-too-large', 'response-too-large', '回答太长，没有保存'),
    # 只读核对原任务之后的第④种结果（8.4）：Codex 那边找不到那一轮。
    ('chat-native-turn-not-returned-no-replay', 'reconcile-not-found', '找不到那一轮的记录。保留原记录，不会重发；要继续请开新对话'),
    ('chat-native-identity-incomplete', 'reconcile-not-found', '找不到那一轮的记录。保留原记录，不会重发；要继续请开新对话'),
    # Added by this backend (not in the 8.4 table; wording follows its 被拦下 rows).
    ('chat-money-cap-not-enforceable', 'money-cap', '服务无法执行金额上限，所以不发送'),
    ('chat-input-version-differs', 'stale-version', '课题输入已更新，这条对话绑定的是旧版本'),
    ('chat-project-differs', 'wrong-project', '这条对话属于另一个课题'),
    ('chat-session-binding-differs', 'wrong-project', '这条对话属于另一个课题'),
    ('chat-continuation-project-stage-not-authorized', 'permit-missing', '这个课题还没有对话许可。许可由本机操作者在页面外准备，写明次数上限和有效期；页面上不能授权。Stage 1 整轮运行的同意书不能代用'),
)
_EXACT = {code: (group, text) for code, group, text in EXACT}

# Families from the 8.4 table: anything mentioning binding / pin / changed.
FAMILY_TEXT = '配置或绑定变了，需要操作者重新核对'
FAMILY_MARKERS = ('binding', 'pin', 'changed')


def explain(code):
    """Return ``{code, group, text}`` for a backend refusal code (never raises)."""
    code = '' if code is None else str(code)
    key = code.split(':', 1)[0]
    hit = _EXACT.get(key)
    if hit is not None:
        return dict(code=code, group=hit[0], text=hit[1])
    lowered = key.lower()
    if lowered.startswith('chat-stage-'):
        # Stage context/provider refusals all mean the stage's real materials are not connected yet.
        return dict(code=code, group='stage-unconnected', text='这一段的材料还没接通，对话关着')
    if any(marker in lowered for marker in FAMILY_MARKERS):
        return dict(code=code, group='binding-changed', text=FAMILY_TEXT)
    return dict(code=code, group='unknown', text=FALLBACK)


def explain_all(codes):
    seen, result = set(), []
    for code in codes:
        item = explain(code)
        if item['code'] not in seen:
            seen.add(item['code'])
            result.append(item)
    return result


# A saved turn stores its failure as ``ExceptionName:code`` (or the bare code). 8.4 "本轮失败的原因".
UNCONFIRMED = '这一轮的结果还没确认'
TURN_FAILURES = (
    (('chat-deadline-native-terminal-unconfirmed',), 'unconfirmed', UNCONFIRMED),
    (('chat-unsupported-native-request', 'chat-unknown-tool'), 'forbidden-request', 'Codex 请求了对话里不允许的操作'),
    (('chat-event-', 'chat-terminal-binding', 'chat-native-thread-differs', 'chat-native-policy', 'chat-native-effort',
      'chat-duplicate-call-binding'), 'mismatched-reply', 'Codex 返回的内容和这一轮对不上'),
    (('chat-response-too-large',), 'response-too-large', '回答太长，没有保存'),
    (('chat-rpc-', 'native-', 'TimeoutError'), 'connection-lost', '和 Codex 的连接断了，需要核对'),
)


def explain_turn_error(error):
    """Plain-Chinese reason for a failed or unconfirmed turn; the raw error stays in technical details."""
    if not error:
        return None
    text = str(error)
    code = text.split(':', 1)[1] if ':' in text and text.split(':', 1)[0].isidentifier() else text
    for prefixes, group, words in TURN_FAILURES:
        if code.startswith(prefixes) or text.startswith(prefixes):
            return dict(code=text, group=group, text=words)
    hit = explain(code)
    return hit if hit['group'] != 'unknown' else dict(code=text, group='unknown', text='这一轮没有完成，原始错误见技术细节')
