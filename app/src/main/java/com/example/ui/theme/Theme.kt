package com.example.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext

private val DarkColorScheme = darkColorScheme(primary = Color(0xFF818CF8), onPrimary = Color(0xFF1E1B4B), primaryContainer = Color(0xFF312E81), onPrimaryContainer = Color(0xFFE0E7FF), secondary = Color(0xFF34D399), onSecondary = Color(0xFF064E3B), secondaryContainer = Color(0xFF065F46), onSecondaryContainer = Color(0xFFA7F3D0), tertiary = AmberTertiary, background = DarkBackground, surface = DarkSurface, surfaceVariant = DarkSurfaceVariant, onBackground = Color(0xFFF8FAFC), onSurface = Color(0xFFF8FAFC))
private val LightColorScheme = lightColorScheme(primary = IndigoPrimary, onPrimary = Color.White, primaryContainer = Color(0xFFEEF2FF), onPrimaryContainer = Color(0xFF312E81), secondary = EmeraldSecondary, onSecondary = Color.White, secondaryContainer = Color(0xFFD1FAE5), onSecondaryContainer = Color(0xFF065F46), tertiary = AmberTertiary, background = LightBackground, surface = LightSurface, surfaceVariant = LightSurfaceVariant, onBackground = Color(0xFF0F172A), onSurface = Color(0xFF0F172A))

@Composable
fun TaskTrackerTheme(darkTheme: Boolean = isSystemInDarkTheme(), dynamicColor: Boolean = false, content: @Composable () -> Unit) {
    val colorScheme = when {
        dynamicColor && Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> if (darkTheme) dynamicDarkColorScheme(LocalContext.current) else dynamicLightColorScheme(LocalContext.current)
        darkTheme -> DarkColorScheme
        else -> LightColorScheme
    }
    MaterialTheme(colorScheme = colorScheme, typography = Typography, content = content)
}
