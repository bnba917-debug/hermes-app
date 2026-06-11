import 'package:flutter/material.dart';

import '../theme/app_theme_mode.dart';
import '../theme/hermes_palette.dart';
import '../theme/hermes_theme.dart';

class ProfileSectionTitle extends StatelessWidget {
  const ProfileSectionTitle(this.title, {super.key});

  final String title;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    return Padding(
      padding: const EdgeInsets.only(left: 4, bottom: 10, top: 4),
      child: Text(
        title.toUpperCase(),
        style: Theme.of(context).textTheme.labelLarge?.copyWith(
              color: p.textSecondary,
              letterSpacing: 1.2,
              fontSize: 11,
              fontWeight: FontWeight.w700,
            ),
      ),
    );
  }
}

class ProfileMenuTile extends StatelessWidget {
  const ProfileMenuTile({
    super.key,
    required this.icon,
    required this.title,
    this.subtitle,
    this.onTap,
    this.trailing,
    this.iconColor,
  });

  final IconData icon;
  final String title;
  final String? subtitle;
  final VoidCallback? onTap;
  final Widget? trailing;
  final Color? iconColor;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(14),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 10, horizontal: 4),
          child: Row(
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(13),
                  color: p.surfaceElevated,
                  border: Border.all(color: p.cardBorder),
                ),
                child: Icon(
                  icon,
                  color: iconColor ?? HermesColors.goldLight,
                  size: 22,
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      title,
                      style: Theme.of(context).textTheme.titleSmall?.copyWith(
                            color: p.textPrimary,
                          ),
                    ),
                    if (subtitle != null) ...[
                      const SizedBox(height: 4),
                      Text(
                        subtitle!,
                        style: Theme.of(context).textTheme.bodySmall?.copyWith(
                              color: p.textSecondary,
                            ),
                      ),
                    ],
                  ],
                ),
              ),
              trailing ??
                  Icon(Icons.chevron_right_rounded, color: p.textMuted, size: 22),
            ],
          ),
        ),
      ),
    );
  }
}

class ProfileThemeSelector extends StatelessWidget {
  const ProfileThemeSelector({
    super.key,
    required this.value,
    required this.onChanged,
  });

  final AppThemeMode value;
  final ValueChanged<AppThemeMode> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: _ThemeOption(
            label: '深色',
            icon: Icons.dark_mode_outlined,
            selected: value == AppThemeMode.dark,
            onTap: () => onChanged(AppThemeMode.dark),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _ThemeOption(
            label: '浅色',
            icon: Icons.light_mode_outlined,
            selected: value == AppThemeMode.light,
            onTap: () => onChanged(AppThemeMode.light),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _ThemeOption(
            label: '系统',
            icon: Icons.brightness_auto_outlined,
            selected: value == AppThemeMode.system,
            onTap: () => onChanged(AppThemeMode.system),
          ),
        ),
      ],
    );
  }
}

class _ThemeOption extends StatelessWidget {
  const _ThemeOption({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    return Material(
      color: Colors.transparent,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 8),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(12),
            color: selected
                ? HermesColors.gold.withValues(alpha: p.isDark ? 0.2 : 0.12)
                : p.surfaceElevated,
            border: Border.all(
              color: selected ? HermesColors.gold : p.cardBorder,
              width: selected ? 1.5 : 1,
            ),
          ),
          child: Column(
            children: [
              Icon(
                icon,
                size: 20,
                color: selected ? HermesColors.goldLight : p.textSecondary,
              ),
              const SizedBox(height: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
                  color: selected ? p.textPrimary : p.textSecondary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class ProfileStatTile extends StatelessWidget {
  const ProfileStatTile({
    super.key,
    required this.label,
    required this.value,
  });

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    final p = context.hermes;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      decoration: BoxDecoration(
        color: p.surfaceElevated,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: p.cardBorder.withValues(alpha: 0.6)),
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              label,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: p.textSecondary,
                  ),
            ),
          ),
          Text(
            value,
            style: Theme.of(context).textTheme.titleSmall?.copyWith(
                  color: HermesColors.goldLight,
                ),
          ),
        ],
      ),
    );
  }
}
