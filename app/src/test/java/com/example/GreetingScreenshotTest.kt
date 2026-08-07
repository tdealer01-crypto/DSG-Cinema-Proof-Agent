package com.example

import androidx.compose.ui.test.junit4.createComposeRule
import com.example.ui.theme.TaskTrackerTheme
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner

@RunWith(RobolectricTestRunner::class)
class GreetingScreenshotTest {
    @get:Rule val composeTestRule = createComposeRule()
    @Test fun themeCanRender() { composeTestRule.setContent { TaskTrackerTheme { } } }
}
