import { SpawnScreenState } from "@/enums/SpawnState";
import {
  Dispatch,
  PropsWithChildren,
  SetStateAction,
  createContext,
  useState,
} from "react";

type SpawnContextType = {
  spawnScreenState: SpawnScreenState;
  firstSpawnScreenState: SpawnScreenState;
  setSpawnScreenState: Dispatch<SetStateAction<SpawnScreenState>>;
};

const FIRST_PAGE = SpawnScreenState.STAKING_CHECK;

export const SpawnContext = createContext<SpawnContextType>({
  spawnScreenState: FIRST_PAGE,
  firstSpawnScreenState: FIRST_PAGE,
  setSpawnScreenState: () => {},
});

export const SpawnProvider = ({ children }: PropsWithChildren) => {
  const [spawnScreenState, setSpawnScreenState] =
    useState<SpawnScreenState>(FIRST_PAGE);
  return (
    <SpawnContext.Provider
      value={{
        firstSpawnScreenState: FIRST_PAGE,
        spawnScreenState,
        setSpawnScreenState,
      }}
    >
      {children}
    </SpawnContext.Provider>
  );
};
