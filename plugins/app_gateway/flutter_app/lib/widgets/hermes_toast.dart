import 'package:flutter/material.dart';

import '../theme/hermes_theme.dart';

void showHermesToast(BuildContext context, String message) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Row(
        children: [
          Icon(
            Icons.info_outline,
            size: 18,
            color: HermesColors.goldLight.withValues(alpha: 0.9),
          ),
          const SizedBox(width: 10),
          Expanded(child: Text(message)),
        ],
      ),
      backgroundColor: HermesColors.stone,
      behavior: SnackBarBehavior.floating,
      margin: const EdgeInsets.all(16),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: const BorderSide(color: HermesColors.glassBorder),
      ),
    ),
  );
}
