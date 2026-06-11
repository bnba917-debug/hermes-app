import 'package:flutter/material.dart';

import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';
import 'chat_screen.dart';
import 'profile_screen.dart';
import 'skills_screen.dart';

/// 主界面：底部导航（对话 / 技能 / 我的）。
class HomeShell extends StatefulWidget {
  const HomeShell({super.key});

  @override
  State<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends State<HomeShell> {
  int _index = 0;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;

    return Scaffold(
      backgroundColor: p.background,
      body: IndexedStack(
        index: _index,
        children: const [
          ChatScreen(),
          SkillsScreen(embedded: true),
          ProfileScreen(),
        ],
      ),
      bottomNavigationBar: DecoratedBox(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(
              color: p.isDark
                  ? HermesColors.goldDim.withValues(alpha: 0.35)
                  : p.cardBorder,
            ),
          ),
        ),
        child: NavigationBar(
          selectedIndex: _index,
          onDestinationSelected: (i) => setState(() => _index = i),
          labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
          destinations: const [
          NavigationDestination(
            icon: Icon(Icons.chat_bubble_outline),
            selectedIcon: Icon(Icons.chat_bubble),
            label: '对话',
          ),
          NavigationDestination(
            icon: Icon(Icons.auto_fix_high_outlined),
            selectedIcon: Icon(Icons.auto_fix_high),
            label: '技能',
          ),
          NavigationDestination(
            icon: Icon(Icons.person_outline),
            selectedIcon: Icon(Icons.person),
            label: '我的',
          ),
          ],
        ),
      ),
    );
  }
}
