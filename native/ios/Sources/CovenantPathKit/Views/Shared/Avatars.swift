#if canImport(UIKit)
import SwiftUI

/// Circular initials avatar (mirrors `InitialsAvatar`): indigo tint, bold initials.
public struct InitialsAvatar: View {
    let name: String?
    let size: CGFloat
    public init(name: String?, size: CGFloat = 36) { self.name = name; self.size = size }

    public var body: some View {
        Text(Initials.of(name))
            .font(.system(size: size * 0.36, weight: .bold))
            .foregroundStyle(Color(hex: 0x283593))           // indigo 800
            .frame(width: size, height: size)
            .background(Color(hex: 0xC5CAE9), in: Circle())   // indigo 100
    }
}

/// Member avatar: shows the stored LCR photo (signed URL) when present, else falls back to initials
/// (also falls back while loading / if the image errors). Mirrors `PhotoAvatar`.
public struct PhotoAvatar: View {
    let name: String?
    let photoURL: String?
    let size: CGFloat
    public init(name: String?, photoURL: String?, size: CGFloat = 36) {
        self.name = name; self.photoURL = photoURL; self.size = size
    }

    public var body: some View {
        if let s = photoURL, let url = URL(string: s), !s.isEmpty {
            // Cached, no-flash avatar (see CachedAvatarImage) — falls back to initials while loading /
            // on error, so list scrolling never stalls on image work.
            CachedAvatarImage(url: url) {
                InitialsAvatar(name: name, size: size)
            }
            .frame(width: size, height: size)
            .clipShape(Circle())
        } else {
            InitialsAvatar(name: name, size: size)
        }
    }
}
#endif
