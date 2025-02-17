import abc
import os

import _pickle as pickle
import numpy as np

from .utils.utils import create_folder


class BaseReplayBuffer(abc.ABC):
    """Base class for replay buffers. Every implemented buffer should be a subclass of this class."""

    @abc.abstractmethod
    def add(self, data):
        """
        Adds data to the buffer

        Args:
            data (tuple): (state, action, reward, next_state)
        """

    @abc.abstractmethod
    def sample(self, batch_size):
        """
        sample a minibatch

        Args:
            batch_size (int): .
        """

    @abc.abstractmethod
    def size(self):
        """
        returns replay buffer size
        """

    @abc.abstractmethod
    def save(self, fname):
        """
        Saves buffer checkpointing information to file for future loading.

        Args:
            fname (str): directory and file name where agent should save all relevant info.
        """

    @abc.abstractmethod
    def load(self, fname):
        """
        Loads buffer from file.

        Args:
            fname (str): directory and file name where buffer checkpoint info is stored.

        Returns:
            True if successfully loaded the buffer. False otherwise.
        """


class CircularReplayBuffer(BaseReplayBuffer):
    """A simple circular replay buffers.

    Args:
            size (int): repaly buffer capacity
            seed (int): Seed for a pseudo-random number generator.
    """

    def __init__(self, size=1e5, seed=42, action_dtype="float32", observation_dtype="float32"):

        self._numpy_rng = np.random.default_rng(seed)
        self._size = int(size)

        self._dtype = {
            "observations": observation_dtype,
            "legal_moves_as_int": "float32",
            "actions": action_dtype,
            "rewards": "float32",
            "next_observations": observation_dtype,
            "next_legal_moves_as_int": "float32",
            "done": "float32",
        }

        self._data = {}
        for data_key in self._dtype:
            self._data[data_key] = [None] * int(size)

        self._write_index = -1
        self._n = 0

    def add(self, data):
        """
        Adds data to the buffer

        Args:
            data (tuple): (observation, action, reward, next_observation, done)
        """
        self._write_index = (self._write_index + 1) % self._size
        self._n = int(min(self._size, self._n + 1))
        for idx, key in enumerate(self._data):
            self._data[key][self._write_index] = np.asarray(data[idx], dtype=self._dtype[key])

    def sample(self, batch_size=32):
        """
        sample a minibatch

        Args:
            batch_size (int): .
        """
        if self._n < batch_size:
            raise IndexError("Buffer does not have batch_size=%d transitions yet." % batch_size)

        indices = self._numpy_rng.choice(self._n, size=batch_size, replace=False)
        rval = {}
        for key in self._data:
            rval[key] = np.asarray([self._data[key][idx] for idx in indices], dtype="float32")

        return rval

    def size(self):
        """
        returns replay buffer size
        """
        return self._n

    def save(self, fname):
        """
        Saves buffer checkpointing information to file for future loading.

        Args:
            fname (str): directory and file name where agent should save all relevant info.
        """
        create_folder(fname)

        sdict = {}
        sdict["size"] = self._size
        sdict["write_index"] = self._write_index
        sdict["n"] = self._n

        full_name = os.path.join(fname, "meta.ckpt")
        with open(full_name, "wb") as f:
            pickle.dump(sdict, f)

        for key in self._data:
            full_name = os.path.join(fname, "{}.npy".format(key))
            with open(full_name, "wb") as f:
                np.save(f, self._data[key])

    def load(self, fname):
        """
        Loads buffer from file.

        Args:
            fname (str): directory and file name where buffer checkpoint info is stored.

        Returns:
            True if successfully loaded the buffer. False otherwise.
        """
        full_name = os.path.join(fname, "meta.ckpt")
        with open(full_name, "rb") as f:
            sdict = pickle.load(f)

        self._size = sdict["size"]
        self._write_index = sdict["write_index"]
        self._n = sdict["n"]

        for key in self._data:
            full_name = os.path.join(fname, "{}.npy".format(key))
            with open(full_name, "rb") as f:
                self._data[key] = np.load(f, allow_pickle=True)


class EfficientCircularBuffer(BaseReplayBuffer):
    """An efficient version of a circular replay buffer that only stores each observation
    once.
    """

    def __init__(
        self,
        capacity=10000,
        stack_size=1,
        n_step=1,
        gamma=0.99,
        observation_shape=(),
        observation_dtype=np.float32,
        action_shape=(),
        action_dtype=np.int8,
        reward_shape=(),
        reward_dtype=np.float32,
        extra_storage_types=None,
        seed=42,
    ):
        """Constructor for EfficientCircularBuffer.
        Args:
            capacity: Total number of observations that can be stored in the buffer.
                Note, this is not the same as the number of transitions that can be
                stored in the buffer.
            capacity: Total number of observations that are stacked in the states
                sampled from the buffer.
            stack_size: The number of frames to stack to create an observation.
            n_step: Horizon used to compute n-step return reward
            gamma: Discounting factor used to compute n-step return reward
            observation_shape: Shape of observations that will be stored in the buffer.
            observation_dtype: Type of observations that will be stored in the buffer.
                This can either be the type itself or string representation of the
                type. The type can be either a native python type or a numpy type. If
                a numpy type, a string of the form np.uint8 or numpy.uint8 is
                acceptable.
            action_shape: Shape of actions that will be stored in the buffer.
            action_dtype: Type of actions that will be stored in the buffer. Format is
                described in the description of observation_dtype.
            action_shape: Shape of actions that will be stored in the buffer.
            action_dtype: Type of actions that will be stored in the buffer. Format is
                described in the description of observation_dtype.
            reward_shape: Shape of rewards that will be stored in the buffer.
            reward_dtype: Type of rewards that will be stored in the buffer. Format is
                described in the description of observation_dtype.
            extra_storage_types: A dictionary describing extra items to store in the
                buffer. The mapping should be from the name of the item to a
                (type, shape) tuple.
            seed: Random seed of numpy random generator used when sampling transitions.
        """
        self._capacity = capacity
        self._specs = {
            "observation": (observation_dtype, observation_shape),
            "done": (np.uint8, ()),
            "action": (action_dtype, action_shape),
            "reward": (reward_dtype, reward_shape),
        }
        if extra_storage_types is not None:
            self._specs.update(extra_storage_types)
        self._storage = self._create_storage(capacity, self._specs)
        self._stack_size = stack_size
        self._n_step = n_step
        self._gamma = gamma
        self._discount = np.asarray(
            [self._gamma ** i for i in range(self._n_step)],
            dtype=self._specs["reward"][0],
        )
        self._episode_start = True
        self._cursor = 0
        self._num_added = 0
        self._rng = np.random.default_rng(seed=seed)

    def size(self):
        """Returns the number of transitions stored in the buffer."""
        return max(
            min(self._num_added, self._capacity) - self._stack_size - self._n_step + 1,
            0,
        )

    def _create_storage(self, capacity, specs):
        """Creates the storage buffer for each type of item in the buffer.
        Args:
            capacity: The capacity of the buffer.
            specs: A dictionary mapping item name to a tuple (type, shape) describing
                the items to be stored in the buffer.
        """
        storage = {}
        for key in specs:
            dtype, shape = specs[key]
            dtype = str_to_dtype(dtype)
            shape = (capacity,) + shape
            storage[key] = np.zeros(shape, dtype=dtype)
        return storage

    def _add_transition(self, **transition):
        """Internal method to add a transition to the buffer."""
        for key in transition:
            self._storage[key][self._cursor] = transition[key]
        self._num_added += 1
        self._cursor = (self._cursor + 1) % self._capacity

    def _pad_buffer(self, pad_length):
        """Adds padding to the buffer. Used when stack_size > 1, and padding needs to
        be added to the beginning of the episode.
        """
        for _ in range(pad_length):
            transition = {key: np.zeros_like(self._storage[key][0]) for key in self._storage}
            self._add_transition(**transition)

    def add(self, observation, action, reward, done, **kwargs):
        """Adds a transition to the buffer.
        The required components of a transition are given as positional arguments. The
        user can pass additional components to store in the buffer as kwargs as long as
        they were defined in the specification in the constructor.
        """

        if self._episode_start:
            self._pad_buffer(self._stack_size - 1)
            self._episode_start = False
        transition = {
            "observation": observation,
            "action": action,
            "reward": reward,
            "done": done,
        }
        transition.update(kwargs)
        if transition.keys() != self._specs.keys():
            raise ValueError("Keys passed do not match replay signature")
        for key in self._specs:
            obj_type = transition[key].dtype if hasattr(transition[key], "dtype") else type(transition[key])
            if not np.can_cast(obj_type, self._specs[key][0], casting="same_kind"):
                raise ValueError(
                    f"Key {key} has wrong dtype. Expected {self._specs[key][0]}," f"received {type(transition[key])}."
                )
        self._add_transition(**transition)

        if done:
            self._episode_start = True

    def _get_from_array(self, array, indices, num_to_access=1):
        """Retrieves consecutive elements in the array, wrapping around if necessary.
        Args:
            array: array to access from
            indices: starts of ranges to access from
            num_to_access: how many consecutive elements to access
        """
        full_indices = np.indices((indices.shape[0], num_to_access))[1]
        full_indices = (full_indices + np.expand_dims(indices, axis=1)) % (
            self.size() + self._stack_size + self._n_step - 1
        )
        return array[full_indices]

    def _get_from_storage(self, key, indices, num_to_access=1):
        """Gets values from storage.
        Args:
            key: The name of the component to retrieve.
            indices: This can be a single int or a 1D numpyp array. The indices are
                adjusted to fall within the current bounds of the buffer.
            num_to_access: how many consecutive elements to access
        """
        if not isinstance(indices, np.ndarray):
            indices = np.array([indices])
        if num_to_access == 0:
            return np.array([])
        elif num_to_access == 1:
            return self._storage[key][indices % (self.size() + self._stack_size + self._n_step - 1)]
        else:
            return self._get_from_array(self._storage[key], indices, num_to_access=num_to_access)

    def _sample_indices(self, batch_size):
        indices = []
        while len(indices) < batch_size:
            start_index = self._rng.integers(self.size()) + self._cursor
            if self._get_from_storage("done", start_index, self._stack_size - 1).any():
                continue
            indices.append(start_index + self._stack_size - 1)
        return np.array(indices)

    def sample(self, batch_size):
        """Sample transitions from the buffer. For a given transition, if it's
        done is True, the next_observation value should not be taken to have any
        meaning.
        """
        if self._num_added < self._stack_size + self._n_step:
            raise ValueError("Not enough transitions added to the buffer to sample")
        indices = self._sample_indices(batch_size)
        batch = {}
        terminals = self._get_from_storage("done", indices, self._n_step)

        if self._n_step == 1:
            is_terminal = terminals
            trajectory_lengths = np.ones(batch_size)
        else:
            is_terminal = terminals.any(axis=1)
            trajectory_lengths = (np.argmax(terminals.astype(bool), axis=1) + 1) * is_terminal + self._n_step * (
                1 - is_terminal
            )
        trajectory_lengths = trajectory_lengths.astype(np.int64)

        for key in self._specs:
            if key == "observation":
                batch[key] = self._get_from_storage(
                    "observation",
                    indices - self._stack_size + 1,
                    num_to_access=self._stack_size,
                )
            elif key == "done":
                batch["done"] = is_terminal
            elif key == "reward":
                rewards = self._get_from_storage("reward", indices, self._n_step)
                if self._n_step == 1:
                    rewards = np.expand_dims(rewards, 1)
                rewards = rewards * np.expand_dims(self._discount, axis=0)

                # Mask out rewards past trajectory length
                mask = np.expand_dims(trajectory_lengths, 1) > np.arange(self._n_step)
                rewards = np.sum(rewards * mask, axis=1)
                batch["reward"] = rewards
            else:
                batch[key] = self._get_from_storage(key, indices)
        batch["next_observation"] = self._get_from_storage(
            "observation",
            indices + trajectory_lengths - self._stack_size + 1,
            num_to_access=self._stack_size,
        )
        return batch

    def save(self, dname):
        """Save the replay buffer.
        Args:
            dname: directory where to save buffer. Should already have been created.
        """
        np.save(os.path.join(dname, "storage.npy"), self._storage)
        state = {
            "episode_start": self._episode_start,
            "cursor": self._cursor,
            "num_added": self._num_added,
            "rng": self._rng,
        }

        with open(os.path.join(dname, "replay.pkl"), "wb") as f:
            pickle.dump(state, f)

    def load(self, dname):
        """Load the replay buffer.
        Args:
            dname: directory where to load buffer from.
        """
        self._storage = np.load(os.path.join(dname, "storage.npy"), allow_pickle=True).item()
        with open(os.path.join(dname, "replay.pkl"), "rb") as f:
            state = pickle.load(f)
        self._episode_start = state["episode_start"]
        self._cursor = state["cursor"]
        self._num_added = state["num_added"]
        self._rng = state["rng"]


def str_to_dtype(dtype):
    if isinstance(dtype, type):
        return dtype
    elif dtype.startswith("np.") or dtype.startswith("numpy."):
        return np.typeDict[dtype.split(".")[1]]
    else:
        type_dict = {
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
        }
        return type_dict[dtype]
