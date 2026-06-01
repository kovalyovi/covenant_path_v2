# kotlinx.serialization — keep generated serializers for our @Serializable models.
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.**
-keepclassmembers class org.membercovenantpath.viewer.model.** {
    *** Companion;
}
-keepclasseswithmembers class org.membercovenantpath.viewer.model.** {
    kotlinx.serialization.KSerializer serializer(...);
}
# Ktor / supabase-kt pull in reflection-free serializers; keep the service loaders.
-keep class io.ktor.** { *; }
-keep class io.github.jan.** { *; }
