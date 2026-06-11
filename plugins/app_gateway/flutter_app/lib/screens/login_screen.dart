import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';

import '../api/hermes_api.dart';
import '../app_root_gate.dart';
import '../state/app_state.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import '../utils/phone_input.dart';
import '../widgets/hermes_form.dart';
import '../widgets/hermes_logo.dart';
import '../widgets/hermes_motion.dart';
import '../widgets/hermes_shell.dart';
import '../widgets/slider_captcha_sheet.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _phone = TextEditingController();
  final _code = TextEditingController();
  final _codeFocus = FocusNode();
  bool _busy = false;
  bool _sendingSms = false;
  int _smsCooldown = 0;
  Timer? _cooldownTimer;
  String? _smsHint;
  String? _smsSentForPhone;

  @override
  void initState() {
    super.initState();
    _code.addListener(_onCodeChanged);
    _phone.addListener(_onPhoneChanged);
  }

  @override
  void dispose() {
    _cooldownTimer?.cancel();
    _code.removeListener(_onCodeChanged);
    _phone.removeListener(_onPhoneChanged);
    _phone.dispose();
    _code.dispose();
    _codeFocus.dispose();
    super.dispose();
  }

  String? _phoneForApi({bool showError = false}) {
    final normalized = normalizePhoneForApi(_phone.text);
    if (normalized != null) return normalized;
    if (showError) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('请输入正确的 11 位中国大陆手机号')),
      );
    }
    return null;
  }

  void _onPhoneChanged() {
    final phone = normalizePhoneForApi(_phone.text);
    if (phone == _smsSentForPhone) return;
    _code.clear();
    _cooldownTimer?.cancel();
    setState(() {
      _smsSentForPhone = null;
      _smsHint = null;
      _smsCooldown = 0;
    });
  }

  bool get _canEnterSmsCode {
    final phone = normalizePhoneForApi(_phone.text);
    return phone != null && phone == _smsSentForPhone;
  }

  void _startCooldown([int seconds = 60]) {
    _cooldownTimer?.cancel();
    setState(() => _smsCooldown = seconds);
    _cooldownTimer = Timer.periodic(const Duration(seconds: 1), (t) {
      if (!mounted) {
        t.cancel();
        return;
      }
      if (_smsCooldown <= 1) {
        t.cancel();
        setState(() => _smsCooldown = 0);
      } else {
        setState(() => _smsCooldown -= 1);
      }
    });
  }

  void _applySmsSuccess(Map<String, dynamic> res, {required String authMode}) {
    final phone = normalizePhoneForApi(_phone.text);
    final auto = res['code'] ?? res['dev_code'];
    if (auto != null) {
      _code.text = auto.toString();
    }
    final compact = MediaQuery.sizeOf(context).width < 420;
    setState(() {
      _smsSentForPhone = phone;
      _smsHint = authMode == 'dev'
          ? (compact
              ? '开发模式：验证码见服务端 dev_sms_code'
              : '开发模式：验证码已下发（未配置真实短信时请在服务端查看 dev_sms_code）')
          : '验证码已发送，请查收短信';
    });
    _startCooldown();
    if (mounted) {
      _codeFocus.requestFocus();
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(res['message']?.toString() ?? '验证码已发送')),
      );
      if (_code.text.trim().length >= 6) {
        unawaited(_submit());
      }
    }
  }

  void _onCodeChanged() {
    if (_busy || _sendingSms || !_canEnterSmsCode) return;
    if (_code.text.trim().length == 6) {
      unawaited(_submit());
    }
  }

  Future<void> _onRequestSmsCode() async {
    final phone = _phoneForApi(showError: true);
    if (phone == null) return;
    if (_sendingSms || _smsCooldown > 0) return;

    final state = context.read<AppState>();
    await state.refreshSmsCaptcha();
    if (!state.smsCaptchaEnabled) {
      await _sendSmsDirect(phone);
      return;
    }

    await SliderCaptchaSheet.show(
      context,
      fetchCaptcha: () => state.api.fetchSmsCaptcha(),
    ).then((verified) async {
      if (verified == null || !mounted) return;

      setState(() => _sendingSms = true);
      try {
        final res = await state.sendLoginSms(
          phone,
          captchaToken: verified.captchaToken,
          captchaAnswer: '${verified.sliderBp}',
        );
        if (mounted) {
          _applySmsSuccess(res, authMode: res['auth_mode']?.toString() ?? '');
        }
      } catch (e) {
        if (mounted) {
          final msg = e is HermesApiException ? e.message : e.toString();
          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text('发送失败: $msg')),
          );
        }
      } finally {
        if (mounted) setState(() => _sendingSms = false);
      }
    });
  }

  Future<void> _sendSmsDirect(String phone) async {
    if (_sendingSms || _smsCooldown > 0) return;
    setState(() => _sendingSms = true);
    final state = context.read<AppState>();
    try {
      final res = await state.sendLoginSms(phone);
      _applySmsSuccess(res, authMode: res['auth_mode']?.toString() ?? '');
    } catch (e) {
      if (mounted) {
        final msg = e is HermesApiException ? e.message : e.toString();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('发送失败: $msg')),
        );
      }
    } finally {
      if (mounted) setState(() => _sendingSms = false);
    }
  }

  Future<void> _submit() async {
    final phone = _phoneForApi(showError: true);
    final code = _code.text.trim();
    if (phone == null || code.length < 6) return;
    if (_busy || !_canEnterSmsCode) return;

    setState(() => _busy = true);
    final state = context.read<AppState>();
    try {
      await state.login(phone, code);
      if (mounted) {
        navigateToRootAfterLogin(context);
      }
    } catch (e) {
      if (mounted) {
        final msg = e is HermesApiException ? e.message : e.toString();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('登录失败: $msg')),
        );
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final fieldStyle = hermesFormTextStyle(context);
    final canRequestSms = !_sendingSms && _smsCooldown == 0;
    final palette = HermesPalette.of(context);
    final phoneDecoration = hermesFormDecoration(
      context,
      labelText: '手机号',
      hintText: '13800139999',
      prefixIcon: Icons.smartphone_outlined,
    ).copyWith(
      prefixText: '+86 ',
      prefixStyle: fieldStyle.copyWith(
        color: palette.textPrimary.withValues(alpha: 0.85),
        fontWeight: FontWeight.w600,
      ),
    );

    return Scaffold(
      resizeToAvoidBottomInset: true,
      body: HermesAmbientBackground(
        animate: true,
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: EdgeInsets.fromLTRB(
                20,
                24,
                20,
                24 + MediaQuery.viewInsetsOf(context).bottom,
              ),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 420),
                child: HermesStaggeredEntrance(
                  children: [
                    const Center(child: HermesLogoMark(size: 72, pulse: true)),
                    const SizedBox(height: 24),
                    const HermesBrandHeader(title: 'Hermes'),
                    const SizedBox(height: 28),
                    HermesFormCard(
                      child: AutofillGroup(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            TextField(
                              controller: _phone,
                              keyboardType: TextInputType.number,
                              textInputAction: TextInputAction.next,
                              enableSuggestions: false,
                              autocorrect: false,
                              autofillHints: const [
                                AutofillHints.telephoneNumber,
                              ],
                              inputFormatters: [
                                FilteringTextInputFormatter.digitsOnly,
                                LengthLimitingTextInputFormatter(11),
                              ],
                              style: fieldStyle,
                              cursorColor: HermesColors.gold,
                              decoration: phoneDecoration,
                            ),
                            const SizedBox(height: 16),
                            SizedBox(
                              width: double.infinity,
                              height: 48,
                              child: OutlinedButton(
                                onPressed: canRequestSms ? _onRequestSmsCode : null,
                                style: OutlinedButton.styleFrom(
                                  foregroundColor: HermesColors.gold,
                                  side: const BorderSide(
                                    color: HermesColors.goldDim,
                                  ),
                                  shape: RoundedRectangleBorder(
                                    borderRadius: BorderRadius.circular(14),
                                  ),
                                ),
                                child: _sendingSms
                                    ? const SizedBox(
                                        width: 20,
                                        height: 20,
                                        child: CircularProgressIndicator(
                                          strokeWidth: 2,
                                        ),
                                      )
                                    : Text(
                                        _smsCooldown > 0
                                            ? '重新发送 (${_smsCooldown}s)'
                                            : (_canEnterSmsCode
                                                ? '重新发送'
                                                : '获取验证码'),
                                        style: const TextStyle(
                                          fontSize: 15,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                              ),
                            ),
                            const SizedBox(height: 16),
                            TextField(
                              controller: _code,
                              focusNode: _codeFocus,
                              keyboardType: TextInputType.number,
                              textInputAction: TextInputAction.done,
                              autofillHints: const [AutofillHints.oneTimeCode],
                              maxLength: 6,
                              enabled: !_busy && _canEnterSmsCode,
                              inputFormatters: [
                                FilteringTextInputFormatter.digitsOnly,
                              ],
                              style: fieldStyle.copyWith(
                                fontSize: 22,
                                letterSpacing: 6,
                                fontWeight: FontWeight.w600,
                              ),
                              textAlign: TextAlign.center,
                              cursorColor: HermesColors.gold,
                              decoration: hermesFormDecoration(
                                context,
                                labelText: '短信验证码',
                                hintText: '6 位验证码',
                                helperText: _smsHint ??
                                    (_canEnterSmsCode
                                        ? (_busy ? '正在登录…' : '输满 6 位自动登录')
                                        : '请先完成滑块验证并获取验证码'),
                                prefixIcon: Icons.lock_outline,
                              ).copyWith(counterText: ''),
                            ),
                            if (_busy) ...[
                              const SizedBox(height: 16),
                              const Center(
                                child: SizedBox(
                                  width: 24,
                                  height: 24,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: HermesColors.gold,
                                  ),
                                ),
                              ),
                            ],
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
