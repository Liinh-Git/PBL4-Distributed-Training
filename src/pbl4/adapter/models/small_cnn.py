"""Small smoke-test CNN. This is not the canonical reference workload."""

from torch import nn


class SmallCNN(nn.Module):
    def __init__(self, num_classes: int = 10):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(3, 4, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool2d((1, 1)),
        )
        self.classifier = nn.Linear(4, num_classes)

    def forward(self, inputs):
        return self.classifier(self.features(inputs).flatten(1))
