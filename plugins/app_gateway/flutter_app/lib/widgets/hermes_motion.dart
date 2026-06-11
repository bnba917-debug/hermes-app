import 'package:flutter/material.dart';

/// 子元素依次淡入上滑（用于表单、卡片列表）。
class HermesStaggeredEntrance extends StatefulWidget {
  const HermesStaggeredEntrance({
    super.key,
    required this.children,
    this.interval = const Duration(milliseconds: 80),
    this.duration = const Duration(milliseconds: 420),
  });

  final List<Widget> children;
  final Duration interval;
  final Duration duration;

  @override
  State<HermesStaggeredEntrance> createState() => _HermesStaggeredEntranceState();
}

class _HermesStaggeredEntranceState extends State<HermesStaggeredEntrance>
    with TickerProviderStateMixin {
  late final List<AnimationController> _controllers;
  late final List<Animation<double>> _fade;
  late final List<Animation<Offset>> _slide;

  @override
  void initState() {
    super.initState();
    _controllers = List.generate(
      widget.children.length,
      (i) => AnimationController(vsync: this, duration: widget.duration),
    );
    _fade = _controllers
        .map((c) => CurvedAnimation(parent: c, curve: Curves.easeOutCubic))
        .toList();
    _slide = _controllers
        .map(
          (c) => Tween<Offset>(
            begin: const Offset(0, 0.08),
            end: Offset.zero,
          ).animate(CurvedAnimation(parent: c, curve: Curves.easeOutCubic)),
        )
        .toList();
    _run();
  }

  Future<void> _run() async {
    for (var i = 0; i < _controllers.length; i++) {
      if (!mounted) return;
      _controllers[i].forward();
      await Future<void>.delayed(widget.interval);
    }
  }

  @override
  void dispose() {
    for (final c in _controllers) {
      c.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: List.generate(widget.children.length, (i) {
        return FadeTransition(
          opacity: _fade[i],
          child: SlideTransition(
            position: _slide[i],
            child: widget.children[i],
          ),
        );
      }),
    );
  }
}

/// 单条消息 / 卡片入场。
class HermesFadeSlideIn extends StatefulWidget {
  const HermesFadeSlideIn({
    super.key,
    required this.child,
    this.delay = Duration.zero,
  });

  final Widget child;
  final Duration delay;

  @override
  State<HermesFadeSlideIn> createState() => _HermesFadeSlideInState();
}

class _HermesFadeSlideInState extends State<HermesFadeSlideIn>
    with SingleTickerProviderStateMixin {
  late final AnimationController _c;
  late final Animation<double> _fade;
  late final Animation<Offset> _slide;

  @override
  void initState() {
    super.initState();
    _c = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 360),
    );
    _fade = CurvedAnimation(parent: _c, curve: Curves.easeOut);
    _slide = Tween<Offset>(
      begin: const Offset(0, 0.12),
      end: Offset.zero,
    ).animate(CurvedAnimation(parent: _c, curve: Curves.easeOutCubic));
    Future<void>.delayed(widget.delay, () {
      if (mounted) _c.forward();
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return FadeTransition(
      opacity: _fade,
      child: SlideTransition(position: _slide, child: widget.child),
    );
  }
}

Route<T> hermesFadeRoute<T>(Widget page) {
  return PageRouteBuilder<T>(
    pageBuilder: (_, __, ___) => page,
    transitionDuration: const Duration(milliseconds: 380),
    reverseTransitionDuration: const Duration(milliseconds: 300),
    transitionsBuilder: (_, animation, __, child) {
      final curved = CurvedAnimation(parent: animation, curve: Curves.easeOutCubic);
      return FadeTransition(
        opacity: curved,
        child: SlideTransition(
          position: Tween<Offset>(
            begin: const Offset(0.04, 0),
            end: Offset.zero,
          ).animate(curved),
          child: child,
        ),
      );
    },
  );
}
