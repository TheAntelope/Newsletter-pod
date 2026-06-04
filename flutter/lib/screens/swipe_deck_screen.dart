import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Interest-learning swipe deck. The top card follows the drag with a clamped
/// rotation and edge "decision" labels; past the threshold it flies off (right
/// = keep / +1, left = skip / -1) and submitSwipe is sent, otherwise it springs
/// back. The two cards behind it peek through, scaled and offset. Pass/Keep
/// buttons drive the same commit without a drag. Matches the iOS `SwipeDeckView`
/// stack (depth 3) and physics.
/// Full-screen Discover tab: the swipe deck under an editorial app bar.
class SwipeDeckScreen extends StatelessWidget {
  const SwipeDeckScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        leading: const Padding(
          padding: EdgeInsets.all(8),
          child: ClawcastLogo(size: 28),
        ),
        title: const Text('Tune your pod'),
      ),
      body: const SafeArea(child: SwipeDeck()),
    );
  }
}

/// The reusable deck (card stack + action bar + load/empty/error states).
/// Used full-screen by [SwipeDeckScreen] and inline in the onboarding wizard.
class SwipeDeck extends StatefulWidget {
  const SwipeDeck({super.key, this.topics});

  /// When set (onboarding), the deck is seeded from these catalog topic names
  /// instead of the user's existing sources.
  final List<String>? topics;

  @override
  State<SwipeDeck> createState() => _SwipeDeckState();
}

class _SwipeDeckState extends State<SwipeDeck>
    with SingleTickerProviderStateMixin {
  static const double _threshold = 110;
  static const double _flyOff = 600;
  static const double _maxAngleDeg = 15;
  static const int _stackDepth = 3;

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
    _controller = AnimationController(vsync: this)
      ..addListener(() => setState(() {}));
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
      final deck = await _app.repository.fetchSwipeDeck(topics: widget.topics);
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

  /// Rotation tracks horizontal drag at ~1° per 18pt, clamped to ±15° — the
  /// iOS feel (`dragOffset.width / 18`).
  double get _angleRadians {
    final deg = (_offset.dx / 18).clamp(-_maxAngleDeg, _maxAngleDeg);
    return deg * math.pi / 180;
  }

  double get _likeOpacity => (_offset.dx / _threshold).clamp(0.0, 1.0);
  double get _passOpacity => (-_offset.dx / _threshold).clamp(0.0, 1.0);

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
      _springBack();
    }
  }

  void _springBack() {
    _dismissing = false;
    _anim = Tween<Offset>(begin: _drag, end: Offset.zero).animate(
      CurvedAnimation(parent: _controller, curve: Curves.easeOutBack),
    );
    _controller.duration = const Duration(milliseconds: 350);
    _controller.forward(from: 0).whenComplete(_finish);
  }

  void _dismiss(int direction) {
    if (_cards.isEmpty || _controller.isAnimating) return;
    _direction = direction;
    _dismissing = true;
    _anim = Tween<Offset>(
      begin: _drag,
      end: Offset(direction * _flyOff, _drag.dy),
    ).animate(CurvedAnimation(parent: _controller, curve: Curves.easeOut));
    _controller.duration = const Duration(milliseconds: 250);
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
  Widget build(BuildContext context) => _body();

  Widget _body() {
    if (_loading) return const Center(child: CircularProgressIndicator());
    if (_error != null) return Center(child: Text(_error!));
    if (_cards.isEmpty) return const _EmptyState();

    final busy = _controller.isAnimating;
    final depth = math.min(_stackDepth, _cards.length);

    return Column(
      children: [
        Expanded(
          child: Padding(
            padding: const EdgeInsets.all(DesignTokens.spacingL),
            child: Stack(
              alignment: Alignment.center,
              children: [
                // Background cards, furthest first.
                for (var i = depth - 1; i >= 1; i--)
                  _BackgroundCard(card: _cards[i], depth: i),
                // Top, draggable card.
                GestureDetector(
                  onPanUpdate: _onPanUpdate,
                  onPanEnd: _onPanEnd,
                  child: Transform.translate(
                    offset: _offset,
                    child: Transform.rotate(
                      angle: _angleRadians,
                      child: Stack(
                        children: [
                          _CardChrome(card: _cards[0]),
                          Positioned(
                            top: DesignTokens.spacingL,
                            left: DesignTokens.spacingL,
                            child: _DecisionLabel(
                              text: 'MORE LIKE THIS',
                              color: const Color(0xFF2E7D32),
                              opacity: _likeOpacity,
                            ),
                          ),
                          Positioned(
                            top: DesignTokens.spacingL,
                            right: DesignTokens.spacingL,
                            child: _DecisionLabel(
                              text: 'PASS',
                              color: const Color(0xFFC62828),
                              opacity: _passOpacity,
                            ),
                          ),
                        ],
                      ),
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
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              _ActionButton(
                icon: Icons.close,
                filled: false,
                onPressed: busy ? null : () => _dismiss(-1),
                semanticLabel: 'Skip',
              ),
              const SizedBox(width: DesignTokens.spacingXl),
              _ActionButton(
                icon: Icons.favorite,
                filled: true,
                onPressed: busy ? null : () => _dismiss(1),
                semanticLabel: 'Keep',
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _CardChrome extends StatelessWidget {
  const _CardChrome({required this.card});

  final SwipeDeckCardDto card;

  static const _months = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', //
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
  ];

  @override
  Widget build(BuildContext context) {
    final d = card.publishedAt.toLocal();
    final date = '${_months[d.month - 1]} ${d.day}, ${d.year}';
    return ConstrainedBox(
      constraints: const BoxConstraints(minHeight: 340),
      child: EditorialCard(
        children: [
          MetaLabel(card.sourceName),
          Text(
            card.title,
            maxLines: 3,
            overflow: TextOverflow.ellipsis,
            style: DesignTokens.typographyTitle
                .copyWith(color: DesignTokens.colorInk),
          ),
          Text(
            card.displaySummary,
            maxLines: 6,
            overflow: TextOverflow.ellipsis,
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorInkSoft),
          ),
          const SizedBox(height: DesignTokens.spacingS),
          Row(
            children: [
              const Icon(Icons.calendar_today_outlined,
                  size: 14, color: DesignTokens.colorMuted),
              const SizedBox(width: 4),
              Text(
                date,
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorMuted),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _BackgroundCard extends StatelessWidget {
  const _BackgroundCard({required this.card, required this.depth});

  final SwipeDeckCardDto card;
  final int depth;

  @override
  Widget build(BuildContext context) {
    final scale = math.max(0.85, 1.0 - depth * 0.05);
    final yOffset = depth * 12.0;
    final opacity = math.max(0.4, 1.0 - depth * 0.2);
    return IgnorePointer(
      child: Transform.translate(
        offset: Offset(0, yOffset),
        child: Transform.scale(
          scale: scale,
          child: Opacity(opacity: opacity, child: _CardChrome(card: card)),
        ),
      ),
    );
  }
}

class _DecisionLabel extends StatelessWidget {
  const _DecisionLabel({
    required this.text,
    required this.color,
    required this.opacity,
  });

  final String text;
  final Color color;
  final double opacity;

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: opacity,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: color, width: 3),
        ),
        child: Text(
          text,
          style: TextStyle(
            color: color,
            fontSize: 18,
            fontWeight: FontWeight.w800,
            letterSpacing: 2,
          ),
        ),
      ),
    );
  }
}

class _ActionButton extends StatelessWidget {
  const _ActionButton({
    required this.icon,
    required this.filled,
    required this.onPressed,
    required this.semanticLabel,
  });

  final IconData icon;
  final bool filled;
  final VoidCallback? onPressed;
  final String semanticLabel;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      label: semanticLabel,
      button: true,
      child: SizedBox(
        width: 64,
        height: 64,
        child: filled
            ? ElevatedButton(
                onPressed: onPressed,
                style: ElevatedButton.styleFrom(
                  backgroundColor: DesignTokens.colorAmber,
                  foregroundColor: Colors.white,
                  disabledBackgroundColor: DesignTokens.colorRule,
                  elevation: 0,
                  shape: const CircleBorder(),
                  padding: EdgeInsets.zero,
                ),
                child: Icon(icon, size: 24),
              )
            : OutlinedButton(
                onPressed: onPressed,
                style: OutlinedButton.styleFrom(
                  foregroundColor: DesignTokens.colorAmberDeep,
                  side: const BorderSide(
                      color: DesignTokens.colorAmber, width: 1.5),
                  shape: const CircleBorder(),
                  padding: EdgeInsets.zero,
                ),
                child: Icon(icon, size: 24),
              ),
      ),
    );
  }
}

class _EmptyState extends StatelessWidget {
  const _EmptyState();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingXl),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const ClawcastLogo(size: 56),
            const SizedBox(height: DesignTokens.spacingM),
            Text(
              'All caught up',
              style: DesignTokens.typographyTitle
                  .copyWith(color: DesignTokens.colorInk),
            ),
            const SizedBox(height: DesignTokens.spacingS),
            Text(
              "You've swiped through everything we've pulled in for your "
              'sources. Check back after your next briefing.',
              textAlign: TextAlign.center,
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorInkSoft),
            ),
          ],
        ),
      ),
    );
  }
}
