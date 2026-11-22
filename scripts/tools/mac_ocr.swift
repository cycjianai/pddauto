import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count >= 2 else {
    fputs("Usage: mac_ocr <image_path>\n", stderr)
    exit(1)
}
let path = CommandLine.arguments[1]
guard let nsImg = NSImage(contentsOfFile: path),
      let cgImg = nsImg.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    fputs("Failed to load image: \(path)\n", stderr)
    exit(2)
}

var results: [[String: Any]] = []
let req = VNRecognizeTextRequest { request, error in
    guard error == nil, let obs = request.results as? [VNRecognizedTextObservation] else { return }
    for o in obs {
        guard let top = o.topCandidates(1).first else { continue }
        let b = o.boundingBox
        results.append([
            "text": top.string,
            "x": Double(b.origin.x),
            "y": Double(b.origin.y),
            "width": Double(b.size.width),
            "height": Double(b.size.height),
        ])
    }
}
req.recognitionLanguages = ["zh-Hans", "en-US"]
req.recognitionLevel = .accurate
req.usesLanguageCorrection = true

let handler = VNImageRequestHandler(cgImage: cgImg, options: [:])
try handler.perform([req])

let payload: [String: Any] = ["observations": results]
let jsonData = try JSONSerialization.data(withJSONObject: payload, options: [])
if let s = String(data: jsonData, encoding: .utf8) {
    print(s)
}
