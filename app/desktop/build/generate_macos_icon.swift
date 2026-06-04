#!/usr/bin/env swift
import AppKit

let outputArgument = CommandLine.arguments.dropFirst().first ?? "icon-1024.png"
let outputURL = URL(fileURLWithPath: outputArgument).standardizedFileURL
let size = 1024.0
let canvasRect = NSRect(x: 0, y: 0, width: size, height: size)

guard let bitmap = NSBitmapImageRep(
    bitmapDataPlanes: nil,
    pixelsWide: Int(size),
    pixelsHigh: Int(size),
    bitsPerSample: 8,
    samplesPerPixel: 4,
    hasAlpha: true,
    isPlanar: false,
    colorSpaceName: .deviceRGB,
    bytesPerRow: 0,
    bitsPerPixel: 0
) else {
    fputs("failed to allocate bitmap\n", stderr)
    exit(1)
}

guard let context = NSGraphicsContext(bitmapImageRep: bitmap) else {
    fputs("failed to create graphics context\n", stderr)
    exit(1)
}

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = context

NSColor.clear.setFill()
canvasRect.fill()

let tileRect = canvasRect.insetBy(dx: 56, dy: 56)
let tilePath = NSBezierPath(roundedRect: tileRect, xRadius: 230, yRadius: 230)
tilePath.addClip()

let backgroundGradient = NSGradient(colorsAndLocations:
    (NSColor(calibratedRed: 0.05, green: 0.19, blue: 0.31, alpha: 1.0), 0.0),
    (NSColor(calibratedRed: 0.06, green: 0.34, blue: 0.37, alpha: 1.0), 0.45),
    (NSColor(calibratedRed: 0.15, green: 0.53, blue: 0.49, alpha: 1.0), 1.0)
)!
backgroundGradient.draw(in: tilePath, angle: -28)

let glowRect = NSRect(x: 150, y: 620, width: 620, height: 260)
let glowPath = NSBezierPath(roundedRect: glowRect, xRadius: 160, yRadius: 160)
NSColor(calibratedRed: 0.83, green: 0.96, blue: 0.91, alpha: 0.14).setFill()
glowPath.fill()

let ringRect = tileRect.insetBy(dx: 152, dy: 152)
let ringPath = NSBezierPath(ovalIn: ringRect)
ringPath.lineWidth = 34
NSColor(calibratedRed: 0.84, green: 0.96, blue: 0.92, alpha: 0.82).setStroke()
ringPath.stroke()

let accentArc = NSBezierPath()
accentArc.appendArc(
    withCenter: NSPoint(x: tileRect.midX, y: tileRect.midY),
    radius: 318,
    startAngle: 210,
    endAngle: 326,
    clockwise: false
)
accentArc.lineWidth = 44
accentArc.lineCapStyle = .round
NSColor(calibratedRed: 0.98, green: 0.79, blue: 0.43, alpha: 0.92).setStroke()
accentArc.stroke()

for nodeCenter in [
    NSPoint(x: tileRect.minX + 272, y: tileRect.maxY - 244),
    NSPoint(x: tileRect.midX + 268, y: tileRect.midY + 178),
    NSPoint(x: tileRect.midX + 212, y: tileRect.minY + 236),
] {
    let nodeRect = NSRect(x: nodeCenter.x - 31, y: nodeCenter.y - 31, width: 62, height: 62)
    let node = NSBezierPath(ovalIn: nodeRect)
    NSColor(calibratedRed: 0.97, green: 0.98, blue: 0.96, alpha: 0.98).setFill()
    node.fill()
    let nodeBorder = NSBezierPath(ovalIn: nodeRect.insetBy(dx: 4, dy: 4))
    nodeBorder.lineWidth = 8
    NSColor(calibratedRed: 0.08, green: 0.28, blue: 0.29, alpha: 0.7).setStroke()
    nodeBorder.stroke()
}

let shadow = NSShadow()
shadow.shadowOffset = NSSize(width: 0, height: -18)
shadow.shadowBlurRadius = 30
shadow.shadowColor = NSColor(calibratedWhite: 0.0, alpha: 0.18)
shadow.set()

let paragraphStyle = NSMutableParagraphStyle()
paragraphStyle.alignment = .center

let foreground = NSColor(calibratedRed: 0.98, green: 0.99, blue: 0.97, alpha: 1.0)
let attributes: [NSAttributedString.Key: Any] = [
    .font: NSFont.systemFont(ofSize: 438, weight: .black),
    .foregroundColor: foreground,
    .paragraphStyle: paragraphStyle,
]
let title = NSAttributedString(string: "M", attributes: attributes)
let titleRect = NSRect(x: tileRect.minX, y: tileRect.minY + 228, width: tileRect.width, height: 420)
title.draw(in: titleRect)

NSGraphicsContext.restoreGraphicsState()

guard let pngData = bitmap.representation(using: .png, properties: [:]) else {
    fputs("failed to encode png\n", stderr)
    exit(1)
}

do {
    try FileManager.default.createDirectory(
        at: outputURL.deletingLastPathComponent(),
        withIntermediateDirectories: true
    )
    try pngData.write(to: outputURL)
} catch {
    fputs("failed to write icon png: \(error)\n", stderr)
    exit(1)
}
