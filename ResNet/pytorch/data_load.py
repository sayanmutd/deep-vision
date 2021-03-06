import os
import random
from os import listdir
from os.path import isfile, join

import cv2
import numpy as np
import torch
import torchvision.transforms.functional as F
from torch.utils.data import DataLoader, Dataset
from torchvision.transforms import Compose, Lambda


class ImageNet2012Dataset(Dataset):
    """
    ImageNet LSVRC 2012 dataset.
    http://www.image-net.org/challenges/LSVRC/2012/nonpub-downloads
    """

    def __init__(self, root_dir, labels_file, transform):
        """
        Args:
            root_dir (string): The directory with all image files (flatten).
            labels_file: The label file path
        """
        self.root_dir = root_dir
        self.images = [
            f for f in listdir(root_dir) if isfile(join(root_dir, f))
        ]
        self.transform = transform
        self.label_to_idx = {}
        self.idx_to_name = {}
        with open(labels_file, 'r') as f:
            line = f.readline()
            idx = 0
            while line:
                line = line.strip()
                parts = line.split(' ')
                label = parts[0]
                name = "".join(parts[1:])
                self.label_to_idx[label] = idx
                self.idx_to_name[idx] = name
                idx += 1
                line = f.readline()

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        image_name = self.images[idx]
        image_path = join(self.root_dir, self.images[idx])

        image = cv2.imread(image_path)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)

        # if there's an alpha channel, get rid of it
        if (len(image.shape) > 2 and image.shape[2] == 4):
            image = image[:, :, 0:3]

        # Train file name is in "n02708093_7537.JPEG" format
        # Val file name is in "n15075141_ILSVRC2012_val_00047144.JPEG" format
        parts = image_name.split('_')
        annotation = self.label_to_idx[parts[0]]
        sample = {'image': image, 'annotation': annotation}

        if self.transform:
            sample = self.transform(sample)

        return sample


class Rescale(object):
    """Rescale the image in a sample to a given size.

    Args:
        output_size (tuple or int): Desired output size. If tuple, output is
            matched to output_size. If int, smaller of image edges is matched
            to output_size keeping aspect ratio the same.
    """

    def __init__(self, output_size):
        assert isinstance(output_size, (int, tuple))
        self.output_size = output_size

    def __call__(self, sample):
        image, annotation = sample['image'], sample['annotation']

        h, w = image.shape[:2]
        if isinstance(self.output_size, int):
            if h > w:
                new_h, new_w = self.output_size * h / w, self.output_size
            else:
                new_h, new_w = self.output_size, self.output_size * w / h
        else:
            new_h, new_w = self.output_size

        new_h, new_w = int(new_h), int(new_w)

        img = cv2.resize(image, (new_w, new_h))

        return {'image': img, 'annotation': annotation}


class RandomHorizontalFlip(object):
    def __init__(self, p=0.5):
        self.p = p

    def __call__(self, sample):
        image, annotation = sample['image'], sample['annotation']
        if random.random() < self.p:
            # https://discuss.pytorch.org/t/torch-from-numpy-not-support-negative-strides/3663
            return {'image': np.fliplr(image).copy(), 'annotation': annotation}
        return {'image': image, 'annotation': annotation}


class RandomCrop(object):
    """Crop randomly the image in a sample.

    Args:
        output_size (tuple or int): Desired output size. If int, square crop
            is made.
    """

    def __init__(self, output_size):
        assert isinstance(output_size, (int, tuple))
        if isinstance(output_size, int):
            self.output_size = (output_size, output_size)
        else:
            assert len(output_size) == 2
            self.output_size = output_size

    def __call__(self, sample):
        image, annotation = sample['image'], sample['annotation']

        h, w = image.shape[:2]
        new_h, new_w = self.output_size

        top = np.random.randint(0, h - new_h)
        left = np.random.randint(0, w - new_w)

        image = image[top:top + new_h, left:left + new_w]

        return {'image': image, 'annotation': annotation}


class CenterCrop(object):
    """Crop the center of the image in a sample.

    Args:
        output_size (tuple or int): Desired output size. If int, square crop
            is made.
    """

    def __init__(self, output_size):
        assert isinstance(output_size, (int, tuple))
        if isinstance(output_size, int):
            self.output_size = (output_size, output_size)
        else:
            assert len(output_size) == 2
            self.output_size = output_size

    def __call__(self, sample):
        image, annotation = sample['image'], sample['annotation']

        h, w = image.shape[:2]
        new_h, new_w = self.output_size

        top = (h - new_h) // 2
        left = (w - new_w) // 2

        image = image[top:top + new_h, left:left + new_w]

        return {'image': image, 'annotation': annotation}


class ToTensor(object):
    """Convert ndarrays in sample to Tensors."""

    def __call__(self, sample):
        image, annotation = sample['image'], sample['annotation']

        # if image is in grayscale and has no color channels, add 3 channels
        if (len(image.shape) == 2):
            image = np.stack((image, ) * 3, axis=-1)

        # swap color axis because
        # numpy image: H x W x C
        # torch image: C X H X W
        image = image.transpose((2, 0, 1))

        return {
            'image': torch.from_numpy(image).float(),
            'annotation': annotation,
        }


class Normalize(object):
    """Normalize the image by given pre-calculated mean and std"""

    def __init__(self, mean, std):
        self.mean = mean
        self.std = std

    def __call__(self, sample):
        image, annotation = sample['image'], sample['annotation']

        return {
            'image': F.normalize(image, self.mean, self.std),
            'annotation': annotation,
        }


class ColorJitter(object):
    """
    This is adapted from https://pytorch.org/docs/stable/_modules/torchvision/transforms/transforms.html#ColorJitter
    Note that you need to put this after ToTensor(), since it consumes tensor image, not ndarray

    Randomly change the brightness, contrast and saturation of an image.

    Args:
        brightness (float): How much to jitter brightness. brightness_factor
            is chosen uniformly from [max(0, 1 - brightness), 1 + brightness].
        contrast (float): How much to jitter contrast. contrast_factor
            is chosen uniformly from [max(0, 1 - contrast), 1 + contrast].
        saturation (float): How much to jitter saturation. saturation_factor
            is chosen uniformly from [max(0, 1 - saturation), 1 + saturation].
        hue(float): How much to jitter hue. hue_factor is chosen uniformly from
            [-hue, hue]. Should be >=0 and <= 0.5.
    """

    def __init__(self, brightness=0, contrast=0, saturation=0, hue=0):
        self.brightness = brightness
        self.contrast = contrast
        self.saturation = saturation
        self.hue = hue

    @staticmethod
    def get_params(brightness, contrast, saturation, hue):
        """Get a randomized transform to be applied on image.

        Arguments are same as that of __init__.

        Returns:
            Transform which randomly adjusts brightness, contrast and
            saturation in a random order.
        """
        transforms = []
        if brightness > 0:
            brightness_factor = random.uniform(
                max(0, 1 - brightness), 1 + brightness)
            transforms.append(
                Lambda(
                    lambda img: F.adjust_brightness(img, brightness_factor)))

        if contrast > 0:
            contrast_factor = random.uniform(
                max(0, 1 - contrast), 1 + contrast)
            transforms.append(
                Lambda(lambda img: F.adjust_contrast(img, contrast_factor)))

        if saturation > 0:
            saturation_factor = random.uniform(
                max(0, 1 - saturation), 1 + saturation)
            transforms.append(
                Lambda(
                    lambda img: F.adjust_saturation(img, saturation_factor)))

        if hue > 0:
            hue_factor = random.uniform(-hue, hue)
            transforms.append(
                Lambda(lambda img: F.adjust_hue(img, hue_factor)))

        random.shuffle(transforms)
        transform = Compose(transforms)

        return transform

    def __call__(self, sample):
        """
        Args:
            sample (dict: numpy Image, Annotation)

        Returns:
            numpy Image: Color jittered image.
            Annotation: image annotation
        """
        image, annotation = sample['image'], sample['annotation']
        image = F.to_pil_image(image, mode='RGB')

        transform = self.get_params(self.brightness, self.contrast,
                                    self.saturation, self.hue)
        image = transform(image)

        return {
            'image': np.asarray(image),
            'annotation': annotation,
        }