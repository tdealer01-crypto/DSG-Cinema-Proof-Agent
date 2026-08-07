plugins {
  alias(libs.plugins.android.application)
  alias(libs.plugins.kotlin.compose)
}

fun String.asBuildConfigLiteral(): String =
  "\"" + replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val dsgBackendBaseUrl = (providers.gradleProperty("ANDROID_DSG_BACKEND_BASE_URL").orNull
  ?: System.getenv("ANDROID_DSG_BACKEND_BASE_URL")
  ?: "http://10.0.2.2:8000/").let { if (it.endsWith("/")) it else "$it/" }
val dsgBackendApiKey = providers.gradleProperty("ANDROID_DSG_BACKEND_API_KEY").orNull
  ?: System.getenv("ANDROID_DSG_BACKEND_API_KEY") ?: ""

android {
  namespace = "com.example"
  compileSdk = 36
  defaultConfig {
    applicationId = "com.aistudio.tasktracker.vxyqzp"
    minSdk = 24
    targetSdk = 36
    versionCode = 4
    versionName = "4.0"
    buildConfigField("String", "DSG_BACKEND_BASE_URL", dsgBackendBaseUrl.asBuildConfigLiteral())
    buildConfigField("String", "DSG_BACKEND_API_KEY", dsgBackendApiKey.asBuildConfigLiteral())
    testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
  }
  buildTypes {
    release {
      isMinifyEnabled = false
      proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
      // Release signing is configured externally; no keystore is committed.
    }
  }
  compileOptions {
    sourceCompatibility = JavaVersion.VERSION_11
    targetCompatibility = JavaVersion.VERSION_11
  }
  buildFeatures { compose = true; buildConfig = true }
  testOptions { unitTests { isIncludeAndroidResources = true } }
}

dependencies {
  implementation(platform(libs.androidx.compose.bom))
  implementation(libs.androidx.activity.compose)
  implementation(libs.androidx.compose.material3)
  implementation(libs.androidx.compose.ui)
  implementation(libs.androidx.compose.ui.tooling.preview)
  implementation(libs.androidx.core.ktx)
  implementation(libs.androidx.lifecycle.runtime.compose)
  implementation(libs.androidx.lifecycle.runtime.ktx)
  implementation(libs.androidx.lifecycle.viewmodel.compose)
  implementation(libs.kotlinx.coroutines.android)
  implementation(libs.kotlinx.coroutines.core)
  implementation(libs.okhttp)
  testImplementation(libs.androidx.compose.ui.test.junit4)
  testImplementation(libs.androidx.core)
  testImplementation(libs.junit)
  testImplementation(libs.robolectric)
  androidTestImplementation(platform(libs.androidx.compose.bom))
  androidTestImplementation(libs.androidx.compose.ui.test.junit4)
  androidTestImplementation(libs.androidx.espresso.core)
  androidTestImplementation(libs.androidx.junit)
  debugImplementation(libs.androidx.compose.ui.test.manifest)
  debugImplementation(libs.androidx.compose.ui.tooling)
}
