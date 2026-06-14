import 'package:flutter/material.dart';

/// Curated icon glyphs for the catalog's topic categories, shared between the
/// onboarding topic chips and the sources catalog group headers so the two stay
/// in sync. Topics not in the map fall back to a neutral default glyph rather
/// than disappearing.
const _topicIcons = <String, IconData>{
  'News': Icons.public,
  'Politics': Icons.account_balance_outlined,
  'Business': Icons.trending_up,
  'Tech': Icons.memory,
  'Strategy': Icons.lightbulb_outline,
  'Personal Finance': Icons.savings_outlined,
  'Science': Icons.science_outlined,
  'Sports': Icons.sports_basketball_outlined,
  'Culture': Icons.theater_comedy_outlined,
  'Health & Wellness': Icons.spa_outlined,
  'Fitness': Icons.fitness_center,
  'Family Life': Icons.family_restroom_outlined,
  'Food & Travel': Icons.restaurant_outlined,
  'Romantasy': Icons.auto_stories_outlined,
  'Podcasts': Icons.podcasts,
};

/// Resolve the curated glyph for [topic], falling back to a neutral label icon.
IconData topicIcon(String topic) =>
    _topicIcons[topic] ?? Icons.label_outline;
