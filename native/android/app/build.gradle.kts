import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Resolve SUPABASE_URL / SUPABASE_ANON_KEY from (in priority order):
//   1. -P gradle properties / ~/.gradle/gradle.properties / project gradle.properties
//   2. environment variables (CI)
// Defaulting to "" so the app builds with no secret committed; the app shows a config
// screen when these are blank (mirrors the Flutter --dart-define / _ConfigError path).
fun secret(name: String): String {
    (project.findProperty(name) as String?)?.let { if (it.isNotBlank()) return it }
    System.getenv(name)?.let { if (it.isNotBlank()) return it }
    return ""
}

android {
    namespace = "org.membercovenantpath.viewer"
    compileSdk = 35

    defaultConfig {
        applicationId = "org.membercovenantpath.viewer"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-poc"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // BuildConfig fields read at runtime via BuildConfig.SUPABASE_URL / SUPABASE_ANON_KEY /
        // BROKER_URL. All default to "" so the app builds with no secret committed — the app then
        // shows a config screen (Supabase) or hides Church-login/admin/report features (broker).
        buildConfigField("String", "SUPABASE_URL", "\"${secret("SUPABASE_URL")}\"")
        buildConfigField("String", "SUPABASE_ANON_KEY", "\"${secret("SUPABASE_ANON_KEY")}\"")
        buildConfigField("String", "BROKER_URL", "\"${secret("BROKER_URL")}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
}

dependencies {
    // AndroidX / lifecycle / activity
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)

    // Compose (BOM-aligned)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)
    implementation(libs.androidx.material.icons.extended)
    implementation(libs.androidx.navigation.compose)
    debugImplementation(libs.androidx.ui.tooling)

    // Images (member photo_url)
    implementation(libs.coil.compose)

    // Biometric app-lock, native passkeys (Credential Manager), persisted prefs (DataStore)
    implementation(libs.androidx.biometric)
    implementation(libs.androidx.fragment) // FragmentActivity host for BiometricPrompt (coherent recent ver)
    implementation(libs.androidx.credentials)
    implementation(libs.androidx.credentials.play.services.auth)
    implementation(libs.androidx.datastore.preferences)

    // Material Components — only to supply the Theme.Material3.* XML launch theme parent.
    implementation(libs.google.android.material)

    // Supabase (auth = gotrue, postgrest) + Ktor engine + serialization
    implementation(platform(libs.supabase.bom))
    implementation(libs.supabase.auth)
    implementation(libs.supabase.postgrest)
    implementation(libs.ktor.client.core)
    implementation(libs.ktor.client.okhttp)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)

    // Unit tests for the pure logic layer (Milestones, OrgBucket, DateParse)
    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)

    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
}
