import 'package:flutter/material.dart';

import '../api/hermes_api.dart';
import '../theme/hermes_theme.dart';

/// Slider verification payload returned when the user aligns the thumb.
class SliderCaptchaResult {
  const SliderCaptchaResult({
    required this.captchaToken,
    required this.sliderBp,
  });

  final String captchaToken;
  final int sliderBp;
}

/// Bottom sheet: drag the thumb to the gold marker, then dismiss.
class SliderCaptchaSheet extends StatefulWidget {
  const SliderCaptchaSheet({
    super.key,
    required this.fetchCaptcha,
  });

  final Future<Map<String, dynamic>> Function() fetchCaptcha;

  static Future<SliderCaptchaResult?> show(
    BuildContext context, {
    required Future<Map<String, dynamic>> Function() fetchCaptcha,
  }) {
    return showModalBottomSheet<SliderCaptchaResult>(
      context: context,
      isScrollControlled: true,
      isDismissible: true,
      enableDrag: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => SliderCaptchaSheet(fetchCaptcha: fetchCaptcha),
    );
  }

  @override
  State<SliderCaptchaSheet> createState() => _SliderCaptchaSheetState();
}

class _SliderCaptchaSheetState extends State<SliderCaptchaSheet> {
  static const double _thumbSize = 44;

  final _trackKey = GlobalKey();

  bool _loading = true;
  String? _error;
  String? _captchaToken;
  double _targetRatio = 0.5;
  int _toleranceBp = 35;
  double _thumbRatio = 0;
  bool _dragging = false;
  bool _completed = false;

  @override
  void initState() {
    super.initState();
    _loadCaptcha();
  }

  Future<void> _loadCaptcha() async {
    setState(() {
      _loading = true;
      _error = null;
      _thumbRatio = 0;
      _completed = false;
    });
    try {
      final res = await widget.fetchCaptcha();
      if (!mounted) return;
      if (res['enabled'] == false) {
        Navigator.of(context).pop();
        return;
      }
      final ratio = res['target_ratio'];
      final tol = res['tolerance_bp'];
      setState(() {
        _captchaToken = res['captcha_token']?.toString();
        _targetRatio = ratio is num ? ratio.toDouble().clamp(0.0, 1.0) : 0.5;
        _toleranceBp = tol is num ? tol.toInt() : 35;
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _loading = false;
        _error = e is HermesApiException ? e.message : e.toString();
      });
    }
  }

  int get _thumbBp => (_thumbRatio * 1000).round().clamp(0, 1000);

  int get _targetBp => (_targetRatio * 1000).round();

  bool get _aligned {
    return (_thumbBp - _targetBp).abs() <= _toleranceBp;
  }

  void _completeIfAligned() {
    if (_completed || _loading || !_aligned) return;
    final token = _captchaToken;
    if (token == null || token.isEmpty) {
      setState(() => _error = '验证码加载失败，请重试');
      return;
    }
    _completed = true;
    Navigator.of(context).pop(
      SliderCaptchaResult(captchaToken: token, sliderBp: _thumbBp),
    );
  }

  void _updateThumbFromGlobal(Offset globalPosition) {
    if (_completed) return;
    final box = _trackKey.currentContext?.findRenderObject() as RenderBox?;
    if (box == null) return;
    final trackWidth = box.size.width;
    final maxTravel = trackWidth - _thumbSize;
    if (maxTravel <= 0) return;
    final local = box.globalToLocal(globalPosition);
    final ratio = (local.dx - _thumbSize / 2).clamp(0.0, maxTravel) / maxTravel;
    setState(() {
      _thumbRatio = ratio;
      _error = null;
    });
  }

  @override
  Widget build(BuildContext context) {
    final palette = Theme.of(context).brightness == Brightness.dark
        ? const Color(0xFF2E2A27)
        : Colors.white;

    return Padding(
      padding: EdgeInsets.only(
        bottom: MediaQuery.viewInsetsOf(context).bottom,
      ),
      child: Container(
        margin: const EdgeInsets.fromLTRB(12, 0, 12, 16),
        padding: const EdgeInsets.fromLTRB(20, 16, 20, 24),
        decoration: BoxDecoration(
          color: palette,
          borderRadius: BorderRadius.circular(20),
          border: Border.all(color: HermesColors.goldDim.withValues(alpha: 0.4)),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Row(
              children: [
                const Icon(Icons.verified_user_outlined,
                    color: HermesColors.gold, size: 20),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    '安全验证',
                    style: TextStyle(
                      fontSize: 16,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                IconButton(
                  onPressed: _completed ? null : () => Navigator.pop(context),
                  icon: const Icon(Icons.close_rounded),
                ),
              ],
            ),
            const SizedBox(height: 8),
            Text(
              '拖动滑块，使圆形按钮对齐金色竖线',
              style: TextStyle(
                fontSize: 13,
                color: Theme.of(context).colorScheme.onSurface.withValues(alpha: 0.7),
              ),
            ),
            const SizedBox(height: 20),
            if (_loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 32),
                child: Center(child: CircularProgressIndicator()),
              )
            else
              LayoutBuilder(
                builder: (context, constraints) {
                  final trackWidth = constraints.maxWidth;
                  final maxTravel = trackWidth - _thumbSize;
                  final thumbLeft = maxTravel * _thumbRatio;
                  final targetLeft =
                      maxTravel * _targetRatio + _thumbSize / 2;

                  return Column(
                    children: [
                      SizedBox(
                        key: _trackKey,
                        height: 56,
                        child: GestureDetector(
                          behavior: HitTestBehavior.opaque,
                          onHorizontalDragStart: _completed
                              ? null
                              : (_) => setState(() => _dragging = true),
                          onHorizontalDragUpdate: _completed
                              ? null
                              : (d) => _updateThumbFromGlobal(d.globalPosition),
                          onHorizontalDragEnd: _completed
                              ? null
                              : (_) {
                                  setState(() => _dragging = false);
                                  _completeIfAligned();
                                },
                          child: Stack(
                            clipBehavior: Clip.none,
                            children: [
                              Positioned(
                                left: 0,
                                right: 0,
                                top: 24,
                                child: Container(
                                  height: 8,
                                  decoration: BoxDecoration(
                                    color: HermesColors.gold.withValues(alpha: 0.12),
                                    borderRadius: BorderRadius.circular(8),
                                    border: Border.all(
                                      color: HermesColors.goldDim.withValues(alpha: 0.35),
                                    ),
                                  ),
                                ),
                              ),
                              Positioned(
                                left: targetLeft - 1,
                                top: 8,
                                child: Column(
                                  children: [
                                    Icon(
                                      Icons.arrow_drop_down,
                                      color: HermesColors.gold,
                                      size: 22,
                                    ),
                                    Container(
                                      width: 3,
                                      height: 36,
                                      decoration: BoxDecoration(
                                        color: HermesColors.gold,
                                        borderRadius: BorderRadius.circular(2),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              Positioned(
                                left: thumbLeft,
                                top: 6,
                                child: IgnorePointer(
                                  child: AnimatedContainer(
                                    duration: const Duration(milliseconds: 120),
                                    width: _thumbSize,
                                    height: _thumbSize,
                                    decoration: BoxDecoration(
                                      shape: BoxShape.circle,
                                      gradient: _aligned
                                          ? HermesTheme.goldGradient
                                          : LinearGradient(
                                              colors: [
                                                HermesColors.stone,
                                                HermesColors.stone
                                                    .withValues(alpha: 0.85),
                                              ],
                                            ),
                                      boxShadow: [
                                        BoxShadow(
                                          color: Colors.black.withValues(
                                            alpha: _dragging ? 0.25 : 0.12,
                                          ),
                                          blurRadius: _dragging ? 12 : 6,
                                          offset: const Offset(0, 3),
                                        ),
                                      ],
                                    ),
                                    child: Icon(
                                      _aligned
                                          ? Icons.check_rounded
                                          : Icons.chevron_right_rounded,
                                      color: HermesColors.obsidian,
                                    ),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        _aligned ? '验证成功' : '拖至金色标记后松手',
                        textAlign: TextAlign.center,
                        style: TextStyle(
                          fontSize: 12,
                          color: _aligned
                              ? HermesColors.gold
                              : Theme.of(context)
                                  .colorScheme
                                  .onSurface
                                  .withValues(alpha: 0.55),
                        ),
                      ),
                    ],
                  );
                },
              ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: const TextStyle(color: HermesColors.errorSoft, fontSize: 12),
                textAlign: TextAlign.center,
              ),
            ],
            if (!_loading && !_completed) ...[
              const SizedBox(height: 16),
              TextButton.icon(
                onPressed: _loadCaptcha,
                icon: const Icon(Icons.refresh_rounded, size: 18),
                label: const Text('换一题'),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
