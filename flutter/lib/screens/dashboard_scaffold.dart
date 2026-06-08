import 'package:flutter/material.dart';

import 'home_screen.dart';
import 'library_screen.dart';
import 'sources_screen.dart';
import 'swipe_deck_screen.dart';

/// Exposes the dashboard's tab switcher to descendant tab screens so AppBar
/// affordances (e.g. tapping the [ClawcastLogo]) can jump between tabs —
/// notably back to Today/home — without threading callbacks through each screen.
class DashboardScope extends InheritedWidget {
  const DashboardScope({
    super.key,
    required this.selectTab,
    required super.child,
  });

  /// Index matches [_DashboardScaffoldState._tabs]: 0 = Today/home.
  final void Function(int index) selectTab;

  /// Pops any pushed sub-screens, then switches to the Today/home tab.
  static void goHome(BuildContext context) {
    Navigator.of(context).popUntil((r) => r.isFirst);
    maybeOf(context)?.selectTab(0);
  }

  static DashboardScope? maybeOf(BuildContext context) =>
      context.dependOnInheritedWidgetOfExactType<DashboardScope>();

  @override
  bool updateShouldNotify(DashboardScope oldWidget) => false;
}

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

  void _selectTab(int index) => setState(() => _index = index);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: DashboardScope(
        selectTab: _selectTab,
        child: IndexedStack(index: _index, children: _tabs),
      ),
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
