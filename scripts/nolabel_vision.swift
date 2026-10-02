import Foundation
import AppKit
import Vision

struct BoundingBox: Codable {
    let x: Int
    let y: Int
    let width: Int
    let height: Int
    let normX: Double
    let normY: Double
    let normWidth: Double
    let normHeight: Double
}

struct TextDetection: Codable {
    let text: String
    let confidence: Float
    let box: BoundingBox
    let isBottomRight: Bool
}

struct RectDetection: Codable {
    let confidence: Float
    let box: BoundingBox
    let isBottomRight: Bool
}

struct VisionAnalysisResult: Codable {
    let filePath: String
    let width: Int
    let height: Int
    let hasBottomRightText: Bool
    let texts: [TextDetection]
    let rectangles: [RectDetection]
}

func analyzeImage(path: String) -> VisionAnalysisResult? {
    let url = URL(fileURLWithPath: path)
    guard let img = NSImage(contentsOf: url),
          let cgImg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
        return nil
    }
    
    let width = Double(cgImg.width)
    let height = Double(cgImg.height)
    
    // 1. Text Recognition Request (Accurate mode)
    let textReq = VNRecognizeTextRequest()
    textReq.recognitionLevel = .accurate
    textReq.usesLanguageCorrection = false
    
    // 2. Rectangle Detection Request
    let rectReq = VNDetectRectanglesRequest()
    rectReq.minimumAspectRatio = 0.05
    rectReq.maximumAspectRatio = 20.0
    rectReq.minimumSize = 0.01
    rectReq.maximumObservations = 50
    rectReq.minimumConfidence = 0.3
    
    let handler = VNImageRequestHandler(cgImage: cgImg, options: [:])
    do {
        try handler.perform([textReq, rectReq])
    } catch {
        return nil
    }
    
    var textDetections: [TextDetection] = []
    var hasBRText = false
    
    for observation in textReq.results ?? [] {
        let text = observation.topCandidates(1).first?.string ?? ""
        let box = observation.boundingBox
        
        let pxX = Int(box.origin.x * width)
        let pxY = Int((1.0 - box.origin.y - box.size.height) * height)
        let pxW = max(1, Int(box.size.width * width))
        let pxH = max(1, Int(box.size.height * height))
        
        let normYTop = 1.0 - box.origin.y - box.size.height
        
        let bbox = BoundingBox(
            x: pxX,
            y: pxY,
            width: pxW,
            height: pxH,
            normX: box.origin.x,
            normY: normYTop,
            normWidth: box.size.width,
            normHeight: box.size.height
        )
        
        // Bottom-right quadrant condition:
        // Must be in bottom 35% (normYTop >= 0.65) and right 40% (box.origin.x >= 0.60)
        // And not a giant full-page text block (normHeight <= 0.10, normWidth <= 0.40)
        let isBR = (box.origin.x >= 0.60 && normYTop >= 0.65 && box.size.height <= 0.10 && box.size.width <= 0.40)
        
        let td = TextDetection(
            text: text,
            confidence: observation.confidence,
            box: bbox,
            isBottomRight: isBR
        )
        textDetections.append(td)
        if isBR {
            hasBRText = true
        }
    }
    
    var rectDetections: [RectDetection] = []
    for observation in rectReq.results ?? [] {
        let box = observation.boundingBox
        let pxX = Int(box.origin.x * width)
        let pxY = Int((1.0 - box.origin.y - box.size.height) * height)
        let pxW = max(1, Int(box.size.width * width))
        let pxH = max(1, Int(box.size.height * height))
        
        let normYTop = 1.0 - box.origin.y - box.size.height
        let isBR = (box.origin.x >= 0.60 && normYTop >= 0.65 && box.size.width <= 0.40 && box.size.height <= 0.20)
        
        let bbox = BoundingBox(
            x: pxX,
            y: pxY,
            width: pxW,
            height: pxH,
            normX: box.origin.x,
            normY: normYTop,
            normWidth: box.size.width,
            normHeight: box.size.height
        )
        
        rectDetections.append(RectDetection(
            confidence: observation.confidence,
            box: bbox,
            isBottomRight: isBR
        ))
    }
    
    return VisionAnalysisResult(
        filePath: path,
        width: Int(width),
        height: Int(height),
        hasBottomRightText: hasBRText,
        texts: textDetections,
        rectangles: rectDetections
    )
}

let args = Array(CommandLine.arguments.dropFirst())
if args.isEmpty {
    fputs("Usage: nolabel_vision [--json] <image_path>\n", stderr)
    exit(1)
}

var targetPath: String? = nil
for arg in args {
    if arg != "--json" && targetPath == nil {
        targetPath = arg
    }
}

guard let path = targetPath else {
    fputs("Error: Missing image path\n", stderr)
    exit(1)
}

guard let result = analyzeImage(path: path) else {
    fputs("Error: Could not analyze image at \(path)\n", stderr)
    exit(2)
}

let encoder = JSONEncoder()
encoder.outputFormatting = .prettyPrinted
if let jsonData = try? encoder.encode(result),
   let jsonString = String(data: jsonData, encoding: .utf8) {
    print(jsonString)
}
