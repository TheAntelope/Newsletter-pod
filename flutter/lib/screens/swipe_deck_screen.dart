import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

/// Interest-learning swipe deck. The top card follows the drag with a clamped
/// rotation; past the threshold it flies off (right = keep / +1, left = skip /
/// -1) and submitSwipe is sent, otherwise it springs back. Skip/Keep buttons do
/// the same without a drag.
class SwipeDeckScreen extends StatefulWidget {
  const SwipeDeckScreen({super.key});

  @override
  State<SwipeDeckScreen> createState() => _SwipeDeckScreenState();
}

class _SwipeDeckScreenState extends State<SwipeDeckScreen>
    with SingleTickerProviderStateMixin {
  static const double _threshold = 110;
  static const double _flyOff = 600;
  static const double _maxAngle = math.pi / 12; // ±15°

  late final AppState _app;
  bool _initialized = false;
  bool _loading = true;
  String? _error;
  final List<SwipeDeckCardDto> _cards = [];

  Offset _drag = Offset.zero;
  late final AnimationController _controller;
  Animation<Offset>? _anim;
  bool _dismissing = false;
  int _direction = 0;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 280),
    )..addListener(() => setState(() {}));
  }

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialized) {
      _initialized = true;
      _app = AppScope.of(context);
      _load();
    }
  }

  Future<void> _load() async {
    try {
      final deck = await _app.repository.fetchSwipeDeck();
      if (!mounted) return;
      setState(() {
        _cards
          ..clear()
          ..addAll(deck.items);
        _loading = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  Offset get _offset => _anim?.value ?? _drag;

  double get _angle =>
      ((_offset.dx / 320) * _maxAngle).clamp(-_maxAngle, _maxAngle);

  void _onPanUpdate(DragUpdateDetails d) {
    if (_controller.isAnimating) return;
    setState(() => _drag += d.delta);
  }

  void _onPanEnd(DragEndDetails d) {
    if (_drag.dx > _threshold) {
      _dismiss(1);
    } else if (_drag.dx < -_threshold) {
      _dismiss(-1);
    } else {
      _animate(Offset.zero, dismiss: false);
    }
  }

  void _dismiss(int direction) {
    if (_cards.isEmpty || _controller.isAnimating) return;
    _direction = direction;
    _animate(Offset(direction * _flyOff, _drag.dy), dismiss: true);
  }

  void _animate(Offset target, {required bool dismiss}) {
    _dismissing = dismiss;
    _anim = Tween<Offset>(begin: _drag, end: target).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeOut),
    );
    _controller.forward(from: 0).whenComplete(_finish);
  }

  void _finish() {
    SwipeDeckCardDto? swiped;
    if (_dismissing && _cards.isNotEmpty) swiped = _cards.first;
    setState(() {
      if (swiped != null) _cards.removeAt(0);
      _drag = Offset.zero;
      _anim = null;
      _dismissing = false;
    });
    _controller.reset();
    if (swiped != null) {
      _app.repository.submitSwipe(swiped.sourceItemDedupeKey, _direction);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Discover')),
      body: SafeArea(child: _body()),
    );
  }

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return Center(child: Text(_error!));
    if (_cards.isEmpty) {
      return Center(
        child: Text(
          'You’re all caught up.',
          style: Theme.of(context).textTheme.titleMedium,
        ),
      );
    }
    final busy = _controller.isAnimating;
    return Column(
      children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(DesignTokens.spacingL),
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (_cards.length > 1)
                  Transform.scale(scale: 0.96, child: _cardSurface(_cards[1])),
                GestureDetector(
                  onPanUpdate: _onPanUpdate,
                  onPanEnd: _onPanEnd,
                  child: Transform.translate(
                    offset: _offset,
                    child: Transform.rotate(
                      angle: _angle,
                      child: _cardSurface(_cards[0]),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(
            DesignTokens.spacingL,
            0,
            DesignTokens.spacingL,
            DesignTokens.spacingL,
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceEvenly,
            children: [
              OutlinedButton.icon(
                onPressed: busy ? null : () => _dismiss(-1),
                icon: const Icon(Icons.close),
                label: const Text('Skip'),
              ),
              ElevatedButton.icon(
                onPressed: busy ? null : () => _dismiss(1),
                icon: const Icon(Icons.favorite),
                label: const Text('Keep'),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _cardSurface(SwipeDeckCardDto card) {
    final text = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingL),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              card.sourceName.toUpperCase(),
              style: text.labelSmall?.copyWith(color: DesignTokens.colorMuted),
            ),
            const SizedBox(height: DesignTokens.spacingS),
            Text(card.title, style: text.titleLarge),
            const SizedBox(height: DesignTokens.spacingM),
            Expanded(
              child: Text(card.displaySummary, style: text.bodyMedium),
            ),
          ],
        ),
      ),
    );
  }
}
