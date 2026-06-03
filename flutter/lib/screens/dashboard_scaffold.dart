import 'package:flutter/material.dart';

import 'home_screen.dart';
import 'library_screen.dart';
import 'sources_screen.dart';
import 'swipe_deck_screen.dart';

/// Signed-in shell: a bottom NavigationBar hosting the primary tabs. IndexedStack
/// keeps each tab's state (and loaded data) alive across switches.
class DashboardScaffold extends StatefulWidget {
  const DashboardScaffold({super.key});

  @override
  State<DashboardScaffold> createState() => _DashboardScaffoldState();
}

class _DashboardScaffoldState extends State<DashboardScaffold> {
  int _index = 0;

  static const _tabs = [
    HomeScreen(),
    SourcesScreen(),
    LibraryScreen(),
    SwipeDeckScreen(),
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _index, children: _tabs),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.today_outlined),
            selectedIcon: Icon(Icons.today),
            label: 'Today',
          ),
          NavigationDestination(
            icon: Icon(Icons.rss_feed_outlined),
            selectedIcon: Icon(Icons.rss_feed),
            label: 'Sources',
          ),
          NavigationDestination(
            icon: Icon(Icons.library_music_outlined),
            selectedIcon: Icon(Icons.library_music),
            label: 'Library',
          ),
          NavigationDestination(
            icon: Icon(Icons.style_outlined),
            selectedIcon: Icon(Icons.style),
            label: 'Discover',
          ),
        ],
      ),
    );
  }
}
