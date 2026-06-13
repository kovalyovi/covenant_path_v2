#if canImport(UIKit)
import SwiftUI
import UIKit

/// A tiny in-memory cache of *decoded* avatar images, keyed by URL.
///
/// Avatars repeat across tabs (Golden Hour, Needs, Table, Baptisms, detail) and re-appear constantly
/// as lazy list rows recycle. SwiftUI's `AsyncImage` re-issues the request and re-decodes on every
/// appearance and shows no image while it does — that flash + redecode is the single biggest source of
/// list-scroll jank after non-lazy layout. Caching the decoded `UIImage` makes a recycled row's avatar
/// appear *instantly* with zero work. Backed by `NSCache`, so it self-evicts under memory pressure.
final class AvatarImageCache: @unchecked Sendable {
    static let shared = AvatarImageCache()
    private let cache = NSCache<NSString, UIImage>()

    private init() {
        cache.countLimit = 600
        cache.totalCostLimit = 48 * 1024 * 1024   // ~48 MB of decoded pixels, then NSCache self-evicts
    }

    func image(for key: String) -> UIImage? { cache.object(forKey: key as NSString) }
    func insert(_ image: UIImage, for key: String) {
        // Cost = decoded byte footprint (w·h·scale²·4), so totalCostLimit is meaningful.
        let px = image.size.width * image.size.height * image.scale * image.scale
        cache.setObject(image, forKey: key as NSString, cost: Int(px) * 4)
    }
}

/// Drop-in replacement for `AsyncImage` for avatars: serves the decoded image from the cache instantly
/// (no flash), otherwise downloads once (honoring `URLSession`'s HTTP cache), decodes, and stores it.
/// Reloads automatically when the URL changes (row recycling reuses the view with a new person).
struct CachedAvatarImage<Fallback: View>: View {
    let url: URL
    let fallback: () -> Fallback

    @State private var image: UIImage? = nil

    // Explicit init (keeps `image` private without making the synthesized memberwise init private).
    init(url: URL, @ViewBuilder fallback: @escaping () -> Fallback) {
        self.url = url
        self.fallback = fallback
    }

    var body: some View {
        Group {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
            } else {
                fallback()
            }
        }
        // `.task(id:)` cancels + restarts when the URL changes, so a recycled row loads the right face.
        .task(id: url) { await load() }
    }

    private func load() async {
        let key = url.absoluteString
        if let cached = AvatarImageCache.shared.image(for: key) {
            if image !== cached { image = cached }
            return
        }
        do {
            var request = URLRequest(url: url)
            request.cachePolicy = .returnCacheDataElseLoad
            let (data, _) = try await URLSession.shared.data(for: request)
            guard !Task.isCancelled, let decoded = UIImage(data: data) else { return }
            AvatarImageCache.shared.insert(decoded, for: key)
            image = decoded
        } catch {
            // Leave the initials fallback in place on any failure (offline, 403 on an expired signed URL).
        }
    }
}
#endif
