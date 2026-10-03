import Foundation
import ImageIO
import UIKit

/// Event photos on this device.
///
/// - Memory: decoded, downsampled images (never full resolution in grids).
/// - Disk: `Caches/EventFacesPhotos/<event>/<photo>-<variant>.jpg`, Data Protection
///   `completeUntilFirstUserAuthentication`, excluded from backup.
/// - Purged on sign-out, account deletion, lost access to an event (403) and when a photo
///   leaves the user's list (grant expired, "not me").
actor PhotoCache {
    static let shared = PhotoCache()

    private let memory = NSCache<NSString, UIImage>()
    let root: URL

    init(root: URL? = nil) {
        self.root = root ?? FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0].appending(path: "EventFacesPhotos", directoryHint: .isDirectory)
        memory.totalCostLimit = 80 * 1024 * 1024  // bytes of decoded pixels
    }

    func fileURL(event: String, photo: String, variant: String) -> URL {
        root.appending(path: Self.safe(event), directoryHint: .isDirectory).appending(path: "\(Self.safe(photo))-\(Self.safe(variant)).jpg")
    }

    /// A cached image downsampled to `maxPixel`, or nil.
    func image(event: String, photo: String, variant: String, maxPixel: CGFloat) -> UIImage? {
        let key = "\(event)/\(photo)/\(variant)/\(Int(maxPixel))" as NSString
        if let hit = memory.object(forKey: key) { return hit }
        let url = fileURL(event: event, photo: photo, variant: variant)
        guard let image = Self.downsample(url: url, maxPixel: maxPixel) else { return nil }
        memory.setObject(image, forKey: key, cost: Self.cost(image))
        return image
    }

    /// Store bytes from the API (protected, excluded from backup) and return the downsampled image.
    func store(_ data: Data, event: String, photo: String, variant: String, maxPixel: CGFloat) throws -> UIImage? {
        let url = fileURL(event: event, photo: photo, variant: variant)
        try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        try data.write(to: url, options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var mutable = url
        try mutable.setResourceValues(values)
        return image(event: event, photo: photo, variant: variant, maxPixel: maxPixel)
    }

    /// Drop everything for one event (lost access, event ended).
    func purge(event: String) {
        memory.removeAllObjects()
        try? FileManager.default.removeItem(at: root.appending(path: Self.safe(event), directoryHint: .isDirectory))
    }

    /// Keep only these photos of an event (grants expire; "not me" removes a match).
    func keepOnly(event: String, photos: Set<String>) {
        let dir = root.appending(path: Self.safe(event), directoryHint: .isDirectory)
        guard let files = try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) else { return }
        for file in files where !photos.contains(String(file.lastPathComponent.split(separator: "-").dropLast().joined(separator: "-"))) {
            try? FileManager.default.removeItem(at: file)
        }
    }

    /// Sign-out and account deletion.
    func purgeAll() {
        memory.removeAllObjects()
        try? FileManager.default.removeItem(at: root)
    }

    // MARK: -

    /// ImageIO thumbnail: decodes straight to the target size (no full-resolution bitmap).
    static func downsample(url: URL, maxPixel: CGFloat) -> UIImage? {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, [kCGImageSourceShouldCache: false] as CFDictionary) else { return nil }
        let options = [
            kCGImageSourceCreateThumbnailFromImageAlways: true,
            kCGImageSourceShouldCacheImmediately: true,
            kCGImageSourceCreateThumbnailWithTransform: true,
            kCGImageSourceThumbnailMaxPixelSize: maxPixel,
        ] as CFDictionary
        guard let cg = CGImageSourceCreateThumbnailAtIndex(source, 0, options) else { return nil }
        return UIImage(cgImage: cg)
    }

    static func cost(_ image: UIImage) -> Int { Int(image.size.width * image.size.height * image.scale * image.scale * 4) }

    /// Ids are UUIDs; anything else can't become a path.
    static func safe(_ component: String) -> String {
        String(component.filter { $0.isLetter || $0.isNumber || $0 == "-" || $0 == "_" }.prefix(64))
    }
}
